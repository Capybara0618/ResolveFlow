package com.resolveflow.commerce.catalog;

import com.resolveflow.shared.shopping.CheckoutWire.*;
import java.sql.Timestamp;
import java.time.*;
import java.util.*;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.core.RowCallbackHandler;
import org.springframework.jdbc.core.namedparam.NamedParameterJdbcTemplate;

/** Page-sized reads within PurchaseReads' single repeatable-read snapshot; no provider or cache I/O. */
final class PurchasePageReader {
    private final NamedParameterJdbcTemplate jdbc;
    private final DraftLines snapshots;

    PurchasePageReader(JdbcTemplate jdbc, DraftLines snapshots) {
        this.jdbc = new NamedParameterJdbcTemplate(jdbc);
        this.snapshots = snapshots;
    }

    private record Published(String attempt, String sku) {}

    private static Instant time(Map<String, Object> row, String column) {
        Object value = row.get(column);
        return value instanceof Timestamp t ? t.toInstant() : ((LocalDateTime) value).toInstant(ZoneOffset.UTC);
    }

    List<Purchase> read(List<String> selected, String merchant, String customer, Instant now) {
        if (selected.isEmpty()) return List.of();
        var drafts = selected.stream()
                .filter(id -> id.startsWith("draft:"))
                .map(id -> id.substring(6))
                .toList();
        var legacy = selected.stream()
                .filter(id -> id.startsWith("order:"))
                .map(id -> id.substring(6))
                .toList();
        var args = new HashMap<String, Object>();
        args.put("merchant", merchant);
        args.put("customer", customer);
        args.put("drafts", drafts);
        args.put("legacy", legacy);
        var headers = new HashMap<String, Map<String, Object>>();
        var children = new HashMap<String, List<com.resolveflow.shared.shopping.MultiCheckoutWire.Line>>();
        var payments = new HashMap<String, Payment>();
        var published = new HashMap<Published, String>();
        if (!drafts.isEmpty()) {
            for (var row : jdbc.queryForList(
                    "SELECT * FROM checkout_draft WHERE merchant_id=:merchant AND customer_id=:customer AND draft_id IN (:drafts)",
                    args)) headers.put((String) row.get("draft_id"), row);
            if (headers.values().stream().anyMatch(row -> "MULTI".equals(row.get("kind"))))
                jdbc.query(
                        "SELECT l.* FROM checkout_draft_line l JOIN checkout_draft d ON d.draft_id=l.draft_id WHERE d.merchant_id=:merchant AND d.customer_id=:customer AND d.draft_id IN (:drafts) AND d.kind='MULTI' ORDER BY l.draft_id,l.sku_id",
                        args,
                        (RowCallbackHandler)
                                rs -> children.computeIfAbsent(rs.getString("draft_id"), ignored -> new ArrayList<>())
                                        .add(DraftLines.row(rs)));
            jdbc.query(
                    "SELECT p.* FROM checkout_payment_attempt p JOIN checkout_draft d ON d.draft_id=p.draft_id WHERE d.merchant_id=:merchant AND d.customer_id=:customer AND d.draft_id IN (:drafts) AND NOT EXISTS(SELECT 1 FROM checkout_payment_attempt newer WHERE newer.draft_id=p.draft_id AND newer.sequence_no>p.sequence_no)",
                    args,
                    (RowCallbackHandler) rs -> payments.put(rs.getString("draft_id"), CheckoutPayments.payment(rs)));
            if (headers.values().stream()
                    .anyMatch(row -> "MULTI".equals(row.get("kind"))
                            && payments.containsKey(row.get("draft_id"))
                            && "SUCCEEDED"
                                    .equals(payments.get(row.get("draft_id")).status())))
                jdbc.query(
                        "SELECT l.* FROM checkout_payment_line l JOIN checkout_payment_attempt p ON p.attempt_id=l.attempt_id JOIN checkout_draft d ON d.draft_id=p.draft_id WHERE d.merchant_id=:merchant AND d.customer_id=:customer AND d.draft_id IN (:drafts) AND d.kind='MULTI' AND p.status='SUCCEEDED'",
                        args,
                        (RowCallbackHandler) rs -> published.put(
                                new Published(rs.getString("attempt_id"), rs.getString("sku_id")),
                                rs.getString("line_id")));
        }
        var old = new HashMap<String, Purchase>();
        var oldLines = new HashMap<String, List<Line>>();
        if (!legacy.isEmpty()) {
            jdbc.query(
                    "SELECT o.*,g.paid_amount,COALESCE(s.name,o.merchant_id) AS store_name FROM orders o JOIN payment_ledger g ON g.order_id=o.order_id LEFT JOIN catalog_store s ON s.store_id=o.merchant_id WHERE o.merchant_id=:merchant AND o.customer_id=:customer AND o.order_id IN (:legacy) AND NOT EXISTS(SELECT 1 FROM checkout_draft d WHERE d.order_id=o.order_id)",
                    args,
                    (RowCallbackHandler) rs -> old.put(
                            rs.getString("order_id"), PurchaseReads.paid(rs, "order:" + rs.getString("order_id"))));
            jdbc.query(
                    "SELECT l.* FROM order_line l JOIN orders o ON o.order_id=l.order_id WHERE o.merchant_id=:merchant AND o.customer_id=:customer AND l.merchant_id=:merchant AND l.customer_id=:customer AND o.order_id IN (:legacy) ORDER BY l.order_id,l.line_id",
                    args,
                    (RowCallbackHandler)
                            rs -> oldLines.computeIfAbsent(rs.getString("order_id"), ignored -> new ArrayList<>())
                                    .add(new Line(
                                            rs.getString("line_id"),
                                            rs.getString("sku"),
                                            rs.getString("product_name"),
                                            rs.getString("variant_text"),
                                            null,
                                            rs.getInt("quantity"),
                                            null,
                                            rs.getLong("line_paid_amount"))));
        }
        var orders = new HashSet<>(old.keySet());
        payments.values().stream()
                .filter(p -> "SUCCEEDED".equals(p.status()))
                .map(Payment::orderId)
                .forEach(orders::add);
        var refunds = new HashMap<String, String>();
        if (!orders.isEmpty()) {
            args.put("orders", orders);
            jdbc.query(
                    "SELECT g.* FROM payment_ledger g JOIN orders o ON o.order_id=g.order_id WHERE o.merchant_id=:merchant AND o.customer_id=:customer AND o.order_id IN (:orders)",
                    args,
                    (RowCallbackHandler) rs -> refunds.put(
                            rs.getString("order_id"),
                            PurchaseReads.refundStatus(
                                    rs.getLong("paid_amount"),
                                    rs.getLong("refunded_amount"),
                                    rs.getLong("reserved_refund_amount"))));
        }
        return selected.stream()
                .map(id -> {
                    if (id.startsWith("order:")) {
                        var row = old.get(id.substring(6));
                        if (row == null) throw new ShoppingService.Refused(404, "NOT_FOUND", "商品或订单不存在");
                        return new Purchase(
                                id,
                                null,
                                merchant,
                                row.storeName(),
                                "PAID",
                                row.totalAmount(),
                                "CNY",
                                row.createdAt(),
                                null,
                                row.paidAt(),
                                row.orderId(),
                                List.copyOf(oldLines.getOrDefault(row.orderId(), List.of())),
                                null,
                                refund(refunds, row.orderId()));
                    }
                    var row = headers.get(id.substring(6));
                    if (row == null) throw new ShoppingService.Refused(404, "NOT_FOUND", "商品或订单不存在");
                    Payment payment = payments.get(id.substring(6));
                    String order = payment != null && "SUCCEEDED".equals(payment.status()) ? payment.orderId() : null;
                    var lines = "SINGLE".equals(row.get("kind"))
                            ? snapshots.read(row)
                            : DraftLines.checked(row, children.getOrDefault(id.substring(6), List.of()));
                    var projection = lines.stream()
                            .map(line -> {
                                String lineId = null;
                                if (order != null) {
                                    lineId = "SINGLE".equals(row.get("kind"))
                                            ? payment.lineId()
                                            : published.get(new Published(payment.attemptId(), line.skuId()));
                                    if (lineId == null)
                                        throw new IllegalStateException("published checkout line is missing");
                                }
                                return new Line(
                                        lineId,
                                        line.skuId(),
                                        line.productName(),
                                        line.variant(),
                                        line.assetKey(),
                                        line.quantity(),
                                        line.unitAmount(),
                                        line.lineAmount());
                            })
                            .toList();
                    String state = "EXPIRED".equals(row.get("close_reason"))
                                    || "WAITING_PAYMENT".equals(row.get("status"))
                                            && !now.isBefore(time(row, "expires_at"))
                            ? "EXPIRED"
                            : (String) row.get("status");
                    return new Purchase(
                            id,
                            id.substring(6),
                            merchant,
                            (String) row.get("store_name"),
                            state,
                            ((Number) row.get("total_amount")).longValue(),
                            "CNY",
                            time(row, "created_at"),
                            time(row, "expires_at"),
                            payment == null ? null : payment.paidAt(),
                            order,
                            projection,
                            payment,
                            order == null ? null : refund(refunds, order));
                })
                .toList();
    }

    private static String refund(Map<String, String> refunds, String order) {
        String value = refunds.get(order);
        if (value == null) throw new IllegalStateException("paid purchase ledger is missing");
        return value;
    }
}
