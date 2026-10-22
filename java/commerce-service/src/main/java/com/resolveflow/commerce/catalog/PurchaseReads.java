package com.resolveflow.commerce.catalog;

import com.resolveflow.shared.shopping.CheckoutWire.*;
import java.nio.charset.StandardCharsets;
import java.sql.ResultSet;
import java.sql.SQLException;
import java.time.Clock;
import java.time.Instant;
import java.util.ArrayList;
import java.util.Base64;
import java.util.List;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

@Service
public class PurchaseReads {
    private final JdbcTemplate jdbc;
    private final ShoppingService shop;
    private final CheckoutPayments payments;
    private final Clock clock;
    private final DraftLines lines;

    public PurchaseReads(
            JdbcTemplate jdbc, ShoppingService shop, CheckoutPayments payments, Clock clock, DraftLines lines) {
        this.jdbc = jdbc;
        this.shop = shop;
        this.payments = payments;
        this.clock = clock;
        this.lines = lines;
    }

    public static String cursor(Purchase item) {
        return Base64.getUrlEncoder()
                .withoutPadding()
                .encodeToString((item.createdAt() + "\n" + item.purchaseId()).getBytes(StandardCharsets.UTF_8));
    }

    public static String[] anchor(String value) {
        if (value == null) return null;
        try {
            if (value.isBlank() || value.length() > 256) throw new IllegalArgumentException();
            var fields = new String(Base64.getUrlDecoder().decode(value), StandardCharsets.UTF_8).split("\n", -1);
            if (fields.length != 2 || !fields[1].matches("(draft|order):[0-9a-fA-F-]{36}"))
                throw new IllegalArgumentException();
            Instant.parse(fields[0]);
            return fields;
        } catch (RuntimeException e) {
            throw new IllegalArgumentException("交易分页标识无效");
        }
    }

    private static ShoppingService.Refused missing() {
        return new ShoppingService.Refused(404, "NOT_FOUND", "商品或订单不存在");
    }

    @Transactional(readOnly = true)
    public Purchases list(String merchant, String customer, String filter, String after, Integer size) {
        int limit = size == null ? 24 : size;
        if (merchant == null || merchant.isBlank() || customer == null || customer.isBlank() || limit < 1 || limit > 48)
            throw new IllegalArgumentException("交易范围或分页参数无效");
        if (filter != null
                && !List.of("WAITING_PAYMENT", "PAYMENT_PENDING", "PAID", "CANCELLED", "EXPIRED")
                        .contains(filter)) throw new IllegalArgumentException("交易状态无效");
        var at = anchor(after);
        String sql = """
            SELECT id FROM (
                SELECT CONCAT('draft:',draft_id) AS id,created_at,
                    CASE WHEN close_reason='EXPIRED' OR (status='WAITING_PAYMENT' AND expires_at<=?) THEN 'EXPIRED' ELSE status END AS state
                FROM checkout_draft WHERE merchant_id=? AND customer_id=?
                UNION ALL
                SELECT CONCAT('order:',o.order_id) AS id,o.created_at,'PAID' AS state
                FROM orders o JOIN payment_ledger g ON g.order_id=o.order_id
                WHERE o.merchant_id=? AND o.customer_id=?
                    AND NOT EXISTS(SELECT 1 FROM checkout_draft d WHERE d.order_id=o.order_id)
            ) t WHERE 1=1
            """;
        var args = new ArrayList<Object>(
                List.of(java.sql.Timestamp.from(Instant.now(clock)), merchant, customer, merchant, customer));
        if (filter != null) {
            sql += " AND state=?";
            args.add(filter);
        }
        if (at != null) {
            sql += " AND (created_at<? OR (created_at=? AND id<?))";
            var time = java.sql.Timestamp.from(Instant.parse(at[0]));
            args.add(time);
            args.add(time);
            args.add(at[1]);
        }
        sql += " ORDER BY created_at DESC,id DESC LIMIT ?";
        args.add(limit + 1);
        var ids = jdbc.queryForList(sql, String.class, args.toArray());
        var items = ids.subList(0, Math.min(limit, ids.size())).stream()
                .map(id -> read(id, merchant, customer))
                .toList();
        return new Purchases(items, ids.size() > limit ? cursor(items.getLast()) : null);
    }

    @Transactional(readOnly = true)
    public Purchase read(String id, String merchant, String customer) {
        if (merchant == null || merchant.isBlank() || customer == null || customer.isBlank())
            throw new IllegalArgumentException("需要可信买家归属");
        if (id != null && id.startsWith("draft:")) {
            String draftId = id.substring(6);
            var d = shop.read(draftId, merchant, customer);
            var p = payments.snapshot(draftId, merchant, customer);
            String order = p != null && p.status().equals("SUCCEEDED") ? p.orderId() : null;
            var snapshot = jdbc.queryForList(
                            "SELECT * FROM checkout_draft WHERE draft_id=? AND merchant_id=? AND customer_id=?",
                            draftId,
                            merchant,
                            customer)
                    .getFirst();
            return new Purchase(
                    id,
                    draftId,
                    merchant,
                    d.storeName(),
                    d.status(),
                    d.totalAmount(),
                    "CNY",
                    d.createdAt(),
                    d.expiresAt(),
                    p == null ? null : p.paidAt(),
                    order,
                    lines.read(snapshot).stream()
                            .map(item -> new Line(
                                    order == null
                                            ? null
                                            : lines.publishedId(snapshot, p.attemptId(), item.skuId(), p.lineId()),
                                    item.skuId(),
                                    item.productName(),
                                    item.variant(),
                                    item.assetKey(),
                                    item.quantity(),
                                    item.unitAmount(),
                                    item.lineAmount()))
                            .toList(),
                    p,
                    order == null ? null : refundStatus(order, merchant, customer));
        }
        if (id == null || !id.startsWith("order:")) throw missing();
        String orderId = id.substring(6);
        var rows = jdbc.query(
                "SELECT o.*,g.paid_amount,COALESCE(s.name,o.merchant_id) AS store_name FROM orders o JOIN payment_ledger g ON g.order_id=o.order_id LEFT JOIN catalog_store s ON s.store_id=o.merchant_id WHERE o.order_id=? AND o.merchant_id=? AND o.customer_id=? AND NOT EXISTS(SELECT 1 FROM checkout_draft d WHERE d.order_id=o.order_id)",
                (rs, n) -> paid(rs, id),
                orderId,
                merchant,
                customer);
        if (rows.isEmpty()) throw missing();
        var order = rows.getFirst();
        var lines = jdbc.query(
                "SELECT * FROM order_line WHERE order_id=? AND merchant_id=? AND customer_id=? ORDER BY line_id",
                (rs, n) -> new Line(
                        rs.getString("line_id"),
                        rs.getString("sku"),
                        rs.getString("product_name"),
                        rs.getString("variant_text"),
                        null,
                        rs.getInt("quantity"),
                        null,
                        rs.getLong("line_paid_amount")),
                orderId,
                merchant,
                customer);
        return new Purchase(
                id,
                null,
                merchant,
                order.storeName(),
                "PAID",
                order.totalAmount(),
                "CNY",
                order.createdAt(),
                null,
                order.paidAt(),
                orderId,
                lines,
                null,
                refundStatus(orderId, merchant, customer));
    }

    private String refundStatus(String id, String merchant, String customer) {
        var rows = jdbc.queryForList(
                "SELECT g.paid_amount,g.refunded_amount,g.reserved_refund_amount FROM payment_ledger g JOIN orders o ON o.order_id=g.order_id WHERE g.order_id=? AND o.merchant_id=? AND o.customer_id=?",
                id,
                merchant,
                customer);
        if (rows.size() != 1) throw new IllegalStateException("paid purchase ledger is missing");
        var row = rows.getFirst();
        long paid = ((Number) row.get("paid_amount")).longValue(),
                refunded = ((Number) row.get("refunded_amount")).longValue(),
                reserved = ((Number) row.get("reserved_refund_amount")).longValue();
        if (paid <= 0 || refunded < 0 || reserved < 0 || refunded > paid || reserved > paid - refunded)
            throw new IllegalStateException("paid purchase ledger is inconsistent");
        return refunded == paid
                ? "REFUNDED"
                : reserved > 0 ? "IN_PROGRESS" : refunded > 0 ? "PARTIALLY_REFUNDED" : "NONE";
    }

    private static Purchase paid(ResultSet rs, String id) throws SQLException {
        return new Purchase(
                id,
                null,
                rs.getString("merchant_id"),
                rs.getString("store_name"),
                "PAID",
                rs.getLong("paid_amount"),
                "CNY",
                rs.getTimestamp("created_at").toInstant(),
                null,
                rs.getTimestamp("paid_at").toInstant(),
                rs.getString("order_id"),
                List.of(),
                null);
    }
}
