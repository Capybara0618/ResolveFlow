package com.resolveflow.commerce.publicapi;

import com.resolveflow.commerce.catalog.*;
import com.resolveflow.shared.shopping.FulfillmentWire.*;
import com.resolveflow.shared.shopping.ShippingWire;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.web.bind.annotation.*;

@RestController
public class PublicMerchantController {
    private final CommerceAccess access;
    private final MerchantTradeService trades;
    private final PurchaseReads purchases;
    private final CheckoutShipping shipping;

    public PublicMerchantController(
            CommerceAccess access, MerchantTradeService trades, PurchaseReads purchases, JdbcTemplate db) {
        this.access = access;
        this.trades = trades;
        this.purchases = purchases;
        shipping = new CheckoutShipping(db);
    }

    @GetMapping("/api/v1/merchant/orders")
    public Trades list(
            @RequestHeader(name = "Authorization", required = false) String auth,
            @RequestParam(required = false) String status,
            @RequestParam(required = false) String cursor,
            @RequestParam(required = false) Integer limit) {
        return trades.list(access.merchant(auth).merchantId(), status, cursor, limit);
    }

    @GetMapping("/api/v1/merchant/orders/{order_id}")
    public Trade read(
            @RequestHeader(name = "Authorization", required = false) String auth, @PathVariable("order_id") String id) {
        return trades.read(id, access.merchant(auth).merchantId());
    }

    @GetMapping("/api/v1/merchant/orders/{order_id}/shipping")
    public ShippingWire.View shipping(
            @RequestHeader(name = "Authorization", required = false) String auth, @PathVariable("order_id") String id) {
        return shipping.merchant(id, access.merchant(auth).merchantId());
    }

    @PostMapping("/api/v1/merchant/orders/{order_id}/simulated-shipment")
    public Fulfillment ship(
            @RequestHeader(name = "Authorization", required = false) String auth,
            @RequestHeader(name = "Idempotency-Key", required = false) String key,
            @PathVariable("order_id") String id,
            @RequestBody ShipRequest body) {
        var p = access.merchant(auth);
        CommerceAccess.key(key);
        if (body.expectedVersion() == null || body.expectedVersion() < 1)
            throw new ShoppingService.Refused(400, "INVALID_ARGUMENT", "需要有效的发货版本");
        return trades.ship(id, new ShipCommand(p.merchantId(), p.subject(), key, body.expectedVersion()));
    }

    @GetMapping("/api/v1/shop/purchases/{purchase_id}/fulfillment")
    public Fulfillment fulfillment(
            @RequestHeader(name = "Authorization", required = false) String auth,
            @PathVariable("purchase_id") String id) {
        return CommerceAccess.owned(access.buyer(auth), s -> {
            var p = purchases.read(id, s.merchantId(), s.buyerId());
            if (!"PAID".equals(p.status()) || p.orderId() == null) throw CommerceAccess.missing();
            return trades.buyer(p.orderId(), s.merchantId(), s.buyerId());
        });
    }
}
