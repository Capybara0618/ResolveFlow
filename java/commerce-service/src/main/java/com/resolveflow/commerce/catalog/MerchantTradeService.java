package com.resolveflow.commerce.catalog;

import com.resolveflow.shared.shopping.FulfillmentWire.*;
import java.nio.charset.StandardCharsets;
import java.sql.Timestamp;
import java.time.Clock;
import java.time.Instant;
import java.util.ArrayList;
import java.util.Base64;
import java.util.List;
import java.util.Map;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

@Service
public class MerchantTradeService {
    private final JdbcTemplate jdbc;
    private final PurchaseReads purchases;
    private final Clock clock;
    private static final List<String> STATES = List.of("NOT_SHIPPED", "IN_TRANSIT", "DELIVERED", "LOST", "UNKNOWN");

    public MerchantTradeService(JdbcTemplate jdbc, PurchaseReads purchases, Clock clock) {
        this.jdbc = jdbc;
        this.purchases = purchases;
        this.clock = clock;
    }

    private static ShoppingService.Refused missing() {
        return new ShoppingService.Refused(404, "NOT_FOUND", "订单不存在");
    }

    private static ShoppingService.Refused conflict(String message) {
        return new ShoppingService.Refused(409, "FULFILLMENT_CONFLICT", message);
    }

    private static Instant instant(Object value) {
        return value instanceof Timestamp time
                ? time.toInstant()
                : ((java.time.LocalDateTime) value).toInstant(java.time.ZoneOffset.UTC);
    }

    private Map<String, Object> owned(String id, String merchant) {
        if (id == null || merchant == null || merchant.isBlank()) throw missing();
        var rows = jdbc.queryForList(
                "SELECT o.*,COALESCE((SELECT CONCAT('draft:',d.draft_id) FROM checkout_draft d WHERE d.order_id=o.order_id AND d.status='PAID'),CONCAT('order:',o.order_id)) AS purchase_id FROM orders o JOIN payment_ledger g ON g.order_id=o.order_id WHERE o.order_id=? AND o.merchant_id=?",
                id,
                merchant);
        if (rows.size() != 1) throw missing();
        return rows.getFirst();
    }

    @Transactional(readOnly = true)
    public Fulfillment buyer(String id, String merchant, String customer) {
        var order = owned(id, merchant);
        if (!order.get("customer_id").equals(customer)) throw missing();
        return fulfillment(id);
    }

    private Fulfillment fulfillment(String id) {
        var heads = jdbc.queryForList("SELECT * FROM order_fulfillment WHERE order_id=?", id);
        var tracking = jdbc.query(
                "SELECT l.line_id,s.status,s.carrier_conclusion,s.source_version FROM order_line l LEFT JOIN shipment s ON s.line_id=l.line_id WHERE l.order_id=? ORDER BY l.line_id",
                (rs, n) -> new Tracking(
                        rs.getString("line_id"),
                        rs.getString("status") == null ? "UNKNOWN" : rs.getString("status"),
                        rs.getString("carrier_conclusion") == null ? "UNKNOWN" : rs.getString("carrier_conclusion"),
                        (Long) rs.getObject("source_version"),
                        List.of()),
                id);
        var complete = new ArrayList<Tracking>();
        Instant latest = null;
        for (var line : tracking) {
            var events = jdbc.query(
                    "SELECT code,occurred_at,source_version FROM shipment_event WHERE line_id=? ORDER BY source_version LIMIT 200",
                    (rs, n) -> new Event(
                            rs.getString("code"),
                            rs.getTimestamp("occurred_at").toInstant(),
                            rs.getLong("source_version")),
                    line.lineId());
            for (var event : events)
                if (latest == null || event.occurredAt().isAfter(latest)) latest = event.occurredAt();
            complete.add(
                    new Tracking(line.lineId(), line.status(), line.carrierConclusion(), line.sourceVersion(), events));
        }
        if (!heads.isEmpty()) {
            var h = heads.getFirst();
            return new Fulfillment(
                    id,
                    (String) h.get("status"),
                    true,
                    ((Number) h.get("version")).longValue(),
                    instant(h.get("updated_at")),
                    complete);
        }
        var distinct = complete.stream().map(Tracking::status).distinct().toList();
        return new Fulfillment(
                id,
                distinct.size() == 1 && STATES.contains(distinct.getFirst()) ? distinct.getFirst() : "UNKNOWN",
                true,
                null,
                latest,
                complete);
    }

    private String blocked(String id, Fulfillment f) {
        if (f.version() == null) return "历史订单只读物流，不支持首次模拟发货";
        if (!f.status().equals("NOT_SHIPPED")) return "该订单已模拟发货";
        var g = jdbc.queryForList(
                        "SELECT paid_amount,refunded_amount,reserved_refund_amount FROM payment_ledger WHERE order_id=?",
                        id)
                .getFirst();
        if (((Number) g.get("refunded_amount")).longValue() != 0
                || ((Number) g.get("reserved_refund_amount")).longValue() != 0) return "订单已有退款或退款占用，不能模拟发货";
        var slots = jdbc.queryForList(
                "SELECT r.state FROM order_line l LEFT JOIN line_refund r ON r.line_id=l.line_id WHERE l.order_id=? ORDER BY l.line_id",
                String.class,
                id);
        if (slots.isEmpty() || slots.stream().anyMatch(s -> !"FREE".equals(s))) return "订单行退款状态待确认，不能模拟发货";
        if (f.lines().size() != slots.size()
                || f.lines().stream()
                        .anyMatch(l -> !l.status().equals("NOT_SHIPPED")
                                || l.sourceVersion() == null
                                || l.sourceVersion() != 1
                                || l.events().size() != 1
                                || !l.events().getFirst().code().equals("ORDER_PAID"))) return "订单履约事实不完整，不能模拟发货";
        return null;
    }

    @Transactional(readOnly = true)
    public Trade read(String id, String merchant) {
        var o = owned(id, merchant);
        var f = fulfillment(id);
        String reason = blocked(id, f);
        return new Trade(
                purchases.read((String) o.get("purchase_id"), merchant, (String) o.get("customer_id")),
                f,
                reason == null,
                reason);
    }

    @Transactional(readOnly = true)
    public Trades list(String merchant, String status, String cursor, Integer size) {
        int limit = size == null ? 24 : size;
        if (merchant == null
                || merchant.isBlank()
                || limit < 1
                || limit > 48
                || (status != null && !STATES.contains(status))) throw new IllegalArgumentException("订单筛选或分页参数无效");
        String sql =
                "SELECT * FROM (SELECT o.order_id,o.created_at,COALESCE(f.status,(SELECT CASE WHEN COUNT(*)=COUNT(s.status) AND COUNT(DISTINCT s.status)=1 THEN MIN(s.status) ELSE 'UNKNOWN' END FROM order_line l LEFT JOIN shipment s ON s.line_id=l.line_id WHERE l.order_id=o.order_id)) AS state FROM orders o JOIN payment_ledger g ON g.order_id=o.order_id LEFT JOIN order_fulfillment f ON f.order_id=o.order_id WHERE o.merchant_id=?) t WHERE 1=1";
        var args = new ArrayList<Object>(List.of(merchant));
        if (status != null) {
            sql += " AND state=?";
            args.add(status);
        }
        if (cursor != null) {
            try {
                var a = new String(Base64.getUrlDecoder().decode(cursor), StandardCharsets.UTF_8).split("\n", -1);
                if (cursor.length() > 512
                        || a.length != 4
                        || !a[0].equals(merchant)
                        || !a[1].equals(status == null ? "" : status)) throw new IllegalArgumentException();
                var time = Timestamp.from(Instant.parse(a[2]));
                UUIDCheck(a[3]);
                sql += " AND (created_at<? OR (created_at=? AND order_id<?))";
                args.add(time);
                args.add(time);
                args.add(a[3]);
            } catch (RuntimeException e) {
                throw new IllegalArgumentException("订单分页标识无效");
            }
        }
        sql += " ORDER BY created_at DESC,order_id DESC LIMIT ?";
        args.add(limit + 1);
        var ids = jdbc.queryForList(sql, args.toArray());
        var items = ids.subList(0, Math.min(limit, ids.size())).stream()
                .map(r -> read((String) r.get("order_id"), merchant))
                .toList();
        String next = null;
        if (ids.size() > limit) {
            var last = ids.get(limit - 1);
            next = Base64.getUrlEncoder()
                    .withoutPadding()
                    .encodeToString((merchant + "\n" + (status == null ? "" : status) + "\n"
                                    + instant(last.get("created_at")) + "\n" + last.get("order_id"))
                            .getBytes(StandardCharsets.UTF_8));
        }
        return new Trades(items, next);
    }

    private static void UUIDCheck(String id) {
        if (!java.util.UUID.fromString(id).toString().equalsIgnoreCase(id)) throw new IllegalArgumentException();
    }
    // Ownership is read before lock acquisition; READ_COMMITTED prevents that early
    // snapshot from hiding a winning refund reservation or original shipment receipt.
    @Transactional(isolation = org.springframework.transaction.annotation.Isolation.READ_COMMITTED)
    public Fulfillment ship(String id, ShipCommand command) {
        if (command == null
                || command.expectedVersion() == null
                || command.expectedVersion() < 1
                || command.actor() == null
                || command.actor().isBlank()
                || command.actor().length() > 128
                || command.idempotencyKey() == null
                || !command.idempotencyKey().matches("[A-Za-z0-9_-]{1,128}"))
            throw new IllegalArgumentException("发货请求无效");
        owned(id, command.merchantId());
        jdbc.queryForList("SELECT order_id FROM payment_ledger WHERE order_id=? FOR UPDATE", id);
        var heads = jdbc.queryForList("SELECT * FROM order_fulfillment WHERE order_id=? FOR UPDATE", id);
        if (heads.size() != 1) throw conflict("历史订单不支持首次模拟发货");
        var h = heads.getFirst();
        if (command.idempotencyKey().equals(h.get("shipment_key"))) {
            if (!command.actor().equals(h.get("shipment_actor"))
                    || command.expectedVersion().longValue() != ((Number) h.get("expected_version")).longValue())
                throw conflict("发货请求标识已用于其他内容");
            return fulfillment(id);
        }
        if (command.expectedVersion().longValue() != ((Number) h.get("version")).longValue())
            throw conflict("履约版本已更新，请刷新订单");
        jdbc.queryForList(
                "SELECT r.line_id FROM line_refund r JOIN order_line l ON l.line_id=r.line_id WHERE l.order_id=? ORDER BY r.line_id FOR UPDATE",
                id);
        var f = fulfillment(id);
        var reason = blocked(id, f);
        if (reason != null) throw conflict(reason);
        var now = Timestamp.from(Instant.now(clock));
        for (var line : f.lines()) {
            if (jdbc.update(
                            "UPDATE shipment SET status='IN_TRANSIT',carrier_conclusion='IN_TRANSIT',source_version=2 WHERE line_id=? AND status='NOT_SHIPPED' AND source_version=1",
                            line.lineId())
                    != 1) throw conflict("物流版本已更新");
            jdbc.update(
                    "INSERT INTO shipment_event(line_id,code,occurred_at,source_version) VALUES(?,'SIMULATED_SHIPPED',?,2)",
                    line.lineId(),
                    now);
        }
        jdbc.update(
                "UPDATE order_fulfillment SET status='IN_TRANSIT',version=2,updated_at=?,shipment_key=?,shipment_actor=?,expected_version=? WHERE order_id=?",
                now,
                command.idempotencyKey(),
                command.actor(),
                command.expectedVersion(),
                id);
        return fulfillment(id);
    }
}
