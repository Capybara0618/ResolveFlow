package com.resolveflow.commerce.catalog;

import com.resolveflow.shared.shopping.CheckoutWire.*;
import com.resolveflow.shared.shopping.ShoppingWire.Draft;
import java.sql.ResultSet;
import java.sql.SQLException;
import java.sql.Timestamp;
import java.time.Clock;
import java.time.Instant;
import java.time.temporal.ChronoUnit;
import java.util.Map;
import java.util.UUID;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Service;
import org.springframework.transaction.PlatformTransactionManager;
import org.springframework.transaction.TransactionDefinition;
import org.springframework.transaction.support.TransactionTemplate;

/** Checkout owns separate short transactions, never an outer transaction around provider I/O. */
@Service
public class CheckoutPayments {
    private final JdbcTemplate jdbc;
    private final ShoppingService shop;
    private final SimulatedCheckoutProvider provider;
    private final Clock clock;
    private final TransactionTemplate tx;

    public CheckoutPayments(
            JdbcTemplate jdbc,
            ShoppingService shop,
            SimulatedCheckoutProvider provider,
            Clock clock,
            PlatformTransactionManager manager) {
        this.jdbc = jdbc;
        this.shop = shop;
        this.provider = provider;
        this.clock = clock;
        tx = new TransactionTemplate(manager);
        tx.setIsolationLevel(TransactionDefinition.ISOLATION_READ_COMMITTED);
        tx.setPropagationBehavior(TransactionDefinition.PROPAGATION_REQUIRES_NEW);
    }

    private static ShoppingService.Refused missing() {
        return new ShoppingService.Refused(404, "NOT_FOUND", "商品或订单不存在");
    }

    private static ShoppingService.Refused conflict() {
        return new ShoppingService.Refused(409, "CHECKOUT_STATE_CHANGED", "订单状态已更新，请先确认原付款结果");
    }

    private Instant now() {
        return Instant.now(clock).truncatedTo(ChronoUnit.MICROS);
    }

    private Map<String, Object> draft(String id, String merchant, String customer, boolean lock) {
        if (merchant == null || merchant.isBlank() || customer == null || customer.isBlank())
            throw new IllegalArgumentException("需要可信买家归属");
        var rows = jdbc.queryForList(
                "SELECT * FROM checkout_draft WHERE draft_id=? AND merchant_id=? AND customer_id=?"
                        + (lock ? " FOR UPDATE" : ""),
                id,
                merchant,
                customer);
        if (rows.isEmpty()) throw missing();
        return rows.getFirst();
    }

    private static Instant instant(Map<String, Object> row, String key) {
        var value = row.get(key);
        return value instanceof Timestamp t
                ? t.toInstant()
                : ((java.time.LocalDateTime) value).toInstant(java.time.ZoneOffset.UTC);
    }

    private static Payment payment(ResultSet rs) throws SQLException {
        boolean success = rs.getString("status").equals("SUCCEEDED");
        Timestamp finished = rs.getTimestamp("finished_at"), paid = rs.getTimestamp("paid_at");
        return new Payment(
                rs.getString("attempt_id"),
                rs.getString("draft_id"),
                rs.getString("status"),
                rs.getLong("total_amount"),
                "CNY",
                rs.getTimestamp("created_at").toInstant(),
                finished == null ? null : finished.toInstant(),
                success ? rs.getString("order_id") : null,
                success ? rs.getString("line_id") : null,
                paid == null ? null : paid.toInstant());
    }

    private Payment latest(String id) {
        var rows = jdbc.query(
                "SELECT * FROM checkout_payment_attempt WHERE draft_id=? ORDER BY sequence_no DESC LIMIT 1",
                (rs, n) -> payment(rs),
                id);
        return rows.isEmpty() ? null : rows.getFirst();
    }

    private Payment reserve(String id, PayCommand c) {
        if (c == null || c.idempotencyKey() == null || !c.idempotencyKey().matches("[A-Za-z0-9_-]{1,128}"))
            throw new IllegalArgumentException("需要有效的付款请求标识");
        return tx.execute(status -> {
            var d = draft(id, c.merchantId(), c.customerId(), true);
            var old = jdbc.query(
                    "SELECT * FROM checkout_payment_attempt WHERE draft_id=? AND idempotency_key=?",
                    (rs, n) -> payment(rs),
                    id,
                    c.idempotencyKey());
            if (!old.isEmpty()) return old.getFirst();
            if (!"WAITING_PAYMENT".equals(d.get("status")) || !now().isBefore(instant(d, "expires_at")))
                throw conflict();
            int seq = jdbc.queryForObject(
                    "SELECT COALESCE(MAX(sequence_no),0)+1 FROM checkout_payment_attempt WHERE draft_id=?",
                    Integer.class,
                    id);
            String attempt = UUID.randomUUID().toString();
            jdbc.update(
                    "INSERT INTO checkout_payment_attempt(attempt_id,draft_id,sequence_no,idempotency_key,total_amount,currency,status,order_id,line_id,created_at) VALUES(?,?,?,?,?,'CNY','UNKNOWN',?,?,?)",
                    attempt,
                    id,
                    seq,
                    c.idempotencyKey(),
                    d.get("total_amount"),
                    UUID.randomUUID().toString(),
                    "SHOP-" + UUID.randomUUID(),
                    Timestamp.from(now()));
            jdbc.update("UPDATE checkout_draft SET status='PAYMENT_PENDING' WHERE draft_id=?", id);
            return latest(id);
        });
    }

    public Payment pay(String id, PayCommand command) {
        var attempt = reserve(id, command);
        if (!attempt.status().equals("UNKNOWN")) return attempt;
        try {
            return settle(
                    id,
                    command.merchantId(),
                    command.customerId(),
                    provider.charge(attempt.attemptId(), attempt.totalAmount()));
        } catch (SimulatedCheckoutProvider.Uncertain e) {
            return current(attempt.attemptId());
        }
    }

    private Payment current(String id) {
        return jdbc.query("SELECT * FROM checkout_payment_attempt WHERE attempt_id=?", (rs, n) -> payment(rs), id)
                .getFirst();
    }

    public Payment inspect(String id, String merchant, String customer) {
        draft(id, merchant, customer, false);
        var p = latest(id);
        if (p == null || !p.status().equals("UNKNOWN")) return p;
        var receipt = provider.lookup(p.attemptId());
        return receipt == null ? p : settle(id, merchant, customer, receipt);
    }

    public Payment snapshot(String id, String merchant, String customer) {
        draft(id, merchant, customer, false);
        return latest(id);
    }

    private Payment settle(String id, String merchant, String customer, SimulatedCheckoutProvider.Receipt receipt) {
        return tx.execute(status -> {
            var d = draft(id, merchant, customer, true);
            var rows = jdbc.queryForList(
                    "SELECT * FROM checkout_payment_attempt WHERE attempt_id=? AND draft_id=? FOR UPDATE",
                    receipt.attemptId(),
                    id);
            if (rows.isEmpty()) throw missing();
            var a = rows.getFirst();
            if (!"UNKNOWN".equals(a.get("status"))) return current(receipt.attemptId());
            if (!"PAYMENT_PENDING".equals(d.get("status"))
                    || receipt.amount() != ((Number) a.get("total_amount")).longValue()
                    || !receipt.attemptId().equals(latest(id).attemptId())) throw conflict();
            if (receipt.status().equals("SUCCEEDED")) {
                String order = (String) a.get("order_id"), line = (String) a.get("line_id");
                Timestamp paid = Timestamp.from(receipt.finishedAt());
                jdbc.update(
                        "INSERT INTO orders(order_id,merchant_id,customer_id,order_status,currency,paid_at,created_at) VALUES(?,?,?,'PAID','CNY',?,?)",
                        order,
                        merchant,
                        customer,
                        paid,
                        d.get("created_at"));
                jdbc.update(
                        "INSERT INTO order_line(line_id,order_id,merchant_id,customer_id,sku,product_name,variant_text,category,quantity,line_paid_amount,currency,paid_at,order_status,version) VALUES(?,?,?,?,?,?,?,?,?,?,'CNY',?,'PAID',1)",
                        line,
                        order,
                        merchant,
                        customer,
                        d.get("sku_id"),
                        d.get("product_name"),
                        d.get("variant"),
                        d.get("category"),
                        d.get("quantity"),
                        d.get("total_amount"),
                        paid);
                jdbc.update(
                        "INSERT INTO payment_ledger(order_id,paid_amount,refunded_amount,reserved_refund_amount,version) VALUES(?,?,0,0,1)",
                        order,
                        d.get("total_amount"));
                jdbc.update(
                        "INSERT INTO line_refund(line_id,state,operation_id,version,updated_at) VALUES(?,'FREE',NULL,1,?)",
                        line,
                        paid);
                jdbc.update(
                        "UPDATE checkout_draft SET status='PAID',order_id=?,line_id=?,paid_at=? WHERE draft_id=?",
                        order,
                        line,
                        paid,
                        id);
                jdbc.update(
                        "UPDATE checkout_payment_attempt SET status='SUCCEEDED',finished_at=?,paid_at=? WHERE attempt_id=?",
                        Timestamp.from(now()),
                        paid,
                        receipt.attemptId());
            } else if (receipt.status().equals("FAILED")) {
                jdbc.update(
                        "UPDATE checkout_payment_attempt SET status='FAILED',finished_at=? WHERE attempt_id=?",
                        Timestamp.from(now()),
                        receipt.attemptId());
                jdbc.update("UPDATE checkout_draft SET status='WAITING_PAYMENT' WHERE draft_id=?", id);
            } else throw new IllegalStateException("unrecognised simulated payment receipt");
            return current(receipt.attemptId());
        });
    }

    public Draft cancel(String id, ScopeCommand command) {
        if (command == null) throw new IllegalArgumentException("需要可信买家归属");
        return tx.execute(status -> {
            var d = draft(id, command.merchantId(), command.customerId(), true);
            if ("CANCELLED".equals(d.get("status"))) return shop.read(id, command.merchantId(), command.customerId());
            if (!"WAITING_PAYMENT".equals(d.get("status")) || !now().isBefore(instant(d, "expires_at")))
                throw conflict();
            jdbc.update("UPDATE checkout_draft SET status='CANCELLED' WHERE draft_id=?", id);
            return shop.read(id, command.merchantId(), command.customerId());
        });
    }
}
