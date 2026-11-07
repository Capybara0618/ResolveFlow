package com.resolveflow.commerce.catalog;

import com.resolveflow.shared.shopping.ShippingWire.*;
import org.springframework.jdbc.core.JdbcTemplate;
import tools.jackson.databind.ObjectMapper;

/** Immutable checkout data, deliberately separate from Agent order/fulfillment projections. */
public class CheckoutShipping {
    private final JdbcTemplate db;
    private final ObjectMapper json = new ObjectMapper();

    public CheckoutShipping(JdbcTemplate db) {
        this.db = db;
    }

    public void requireSnapshot(Selection choice, Snapshot snapshot) {
        if (choice == null && snapshot != null) throw new IllegalArgumentException("请选择收货地址");
        if (choice != null && snapshot == null)
            throw new ShoppingService.Refused(404, "SHIPPING_NOT_CAPTURED", "订单尚未提交");
        if (choice != null
                && (choice.address_id() == null
                        || choice.expected_version() == null
                        || snapshot.version() != choice.expected_version()
                        || !choice.address_id().equals(snapshot.address_id())))
            throw new IllegalArgumentException("收货信息版本无效");
    }

    public void freeze(String draft, Selection choice, Snapshot snapshot, boolean creating) {
        db.queryForList("SELECT draft_id FROM checkout_draft WHERE draft_id=? FOR UPDATE", String.class, draft);
        var old = db.queryForList("SELECT snapshot_json FROM checkout_shipping WHERE draft_id=?", String.class, draft);
        if (!old.isEmpty()) {
            var saved = json.readValue(old.getFirst(), Snapshot.class);
            if (choice == null
                    || !saved.address_id().equals(choice.address_id())
                    || choice.expected_version() == null
                    || saved.version() != choice.expected_version()
                    || (snapshot != null && !saved.equals(snapshot)))
                throw new ShoppingService.Refused(409, "IDEMPOTENCY_CONFLICT", "请求标识已用于不同的收货信息，请查阅原订单");
        } else if (choice != null) {
            if (!creating) throw new ShoppingService.Refused(409, "IDEMPOTENCY_CONFLICT", "原订单未记录此收货信息，请重新确认订单");
            requireSnapshot(choice, snapshot);
            db.update(
                    "INSERT INTO checkout_shipping(draft_id,snapshot_json) VALUES(?,?)",
                    draft,
                    json.writeValueAsString(snapshot));
        }
    }

    public View buyer(String purchase, String merchant, String customer) {
        String column = purchase.startsWith("draft:") ? "draft_id" : "order_id";
        if (!(purchase.startsWith("draft:") || purchase.startsWith("order:")))
            throw new IllegalArgumentException("订单标识无效");
        var rows = db.queryForList(
                "SELECT draft_id FROM checkout_draft WHERE " + column + "=? AND merchant_id=? AND buyer_id=?",
                String.class,
                purchase.substring(6),
                merchant,
                customer);
        if (rows.isEmpty()) {
            if (purchase.startsWith("order:")
                    && !db.queryForList(
                                    "SELECT order_id FROM orders WHERE order_id=? AND merchant_id=? AND buyer_id=?",
                                    String.class,
                                    purchase.substring(6),
                                    merchant,
                                    customer)
                            .isEmpty()) return new View(null);
            throw new ShoppingService.Refused(404, "NOT_FOUND", "订单不存在");
        }
        return view(rows.getFirst());
    }

    public View merchant(String order, String merchant) {
        var customers = db.queryForList(
                "SELECT buyer_id FROM orders WHERE order_id=? AND merchant_id=?", String.class, order, merchant);
        if (customers.isEmpty()) throw new ShoppingService.Refused(404, "NOT_FOUND", "订单不存在");
        return buyer("order:" + order, merchant, customers.getFirst());
    }

    private View view(String draft) {
        var rows = db.queryForList("SELECT snapshot_json FROM checkout_shipping WHERE draft_id=?", String.class, draft);
        return new View(rows.isEmpty() ? null : json.readValue(rows.getFirst(), Snapshot.class));
    }
}
