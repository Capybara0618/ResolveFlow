package com.resolveflow.commerce.publicapi;

import com.resolveflow.commerce.catalog.*;
import com.resolveflow.shared.shopping.CheckoutWire.*;
import com.resolveflow.shared.shopping.ShippingWire;
import com.resolveflow.shared.shopping.ShoppingWire.*;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.web.bind.annotation.*;

@RestController
@RequestMapping("/api/v1/shop")
public class PublicCheckoutController {
    private final CommerceAccess access;
    private final ShoppingService shopping;
    private final CheckoutPayments payments;
    private final PurchaseReads purchases;
    private final BuyerPurchaseReads buyers;
    private final CheckoutShipping shipping;

    public PublicCheckoutController(
            CommerceAccess access,
            ShoppingService shopping,
            CheckoutPayments payments,
            PurchaseReads purchases,
            BuyerPurchaseReads buyers,
            JdbcTemplate db) {
        this.access = access;
        this.shopping = shopping;
        this.payments = payments;
        this.purchases = purchases;
        this.buyers = buyers;
        this.shipping = new CheckoutShipping(db);
    }

    @PostMapping("/drafts")
    public Draft create(
            @RequestHeader(name = "Authorization", required = false) String auth,
            @RequestHeader(name = "Idempotency-Key", required = false) String key,
            @RequestBody DraftRequest request) {
        var actor = access.buyer(auth);
        CommerceAccess.key(key);
        if (request.shipping() == null) throw new ShoppingService.Refused(400, "ADDRESS_REQUIRED", "请选择收货地址");
        try {
            // Probe every trusted store before requesting mutable account data. This also replays
            // a second-store draft after the selected address has been deleted or changed.
            return CommerceAccess.owned(
                    actor, s -> shopping.create(new DraftCommand(s.merchantId(), s.buyerId(), key, request)));
        } catch (ShoppingService.Refused e) {
            if (e.status != 404) throw e;
        }
        var snapshot = access.shipping(auth, request.shipping());
        return CommerceAccess.owned(
                actor, s -> shopping.create(new DraftCommand(s.merchantId(), s.buyerId(), key, request, snapshot)));
    }

    @GetMapping("/drafts/{draft_id}")
    public Draft read(
            @RequestHeader(name = "Authorization", required = false) String auth, @PathVariable("draft_id") String id) {
        return CommerceAccess.owned(access.buyer(auth), s -> shopping.read(id, s.merchantId(), s.buyerId()));
    }

    @PostMapping("/drafts/{draft_id}/payment")
    public Payment pay(
            @RequestHeader(name = "Authorization", required = false) String auth,
            @RequestHeader(name = "Idempotency-Key", required = false) String key,
            @PathVariable("draft_id") String id,
            @RequestBody EmptyRequest body) {
        var actor = access.buyer(auth);
        CommerceAccess.key(key);
        return CommerceAccess.owned(actor, s -> payments.pay(id, new PayCommand(s.merchantId(), s.buyerId(), key)));
    }

    @GetMapping("/drafts/{draft_id}/payment")
    public Lookup payment(
            @RequestHeader(name = "Authorization", required = false) String auth, @PathVariable("draft_id") String id) {
        return CommerceAccess.owned(
                access.buyer(auth), s -> new Lookup(payments.inspect(id, s.merchantId(), s.buyerId())));
    }

    @PostMapping("/drafts/{draft_id}/cancel")
    public Draft cancel(
            @RequestHeader(name = "Authorization", required = false) String auth,
            @PathVariable("draft_id") String id,
            @RequestBody EmptyRequest body) {
        return CommerceAccess.owned(
                access.buyer(auth), s -> payments.cancel(id, new ScopeCommand(s.merchantId(), s.buyerId())));
    }

    @GetMapping("/purchases")
    public Purchases list(
            @RequestHeader(name = "Authorization", required = false) String auth,
            @RequestParam(name = "store_id", required = false) String store,
            @RequestParam(required = false) String status,
            @RequestParam(required = false) String cursor,
            @RequestParam(required = false) Integer limit) {
        return buyers.list(access.buyer(auth), store, status, cursor, limit);
    }

    @GetMapping("/purchases/{purchase_id}")
    public Purchase purchase(
            @RequestHeader(name = "Authorization", required = false) String auth,
            @PathVariable("purchase_id") String id) {
        return CommerceAccess.owned(access.buyer(auth), s -> purchases.read(id, s.merchantId(), s.buyerId()));
    }

    @GetMapping("/purchases/{purchase_id}/shipping")
    public ShippingWire.View shipping(
            @RequestHeader(name = "Authorization", required = false) String auth,
            @PathVariable("purchase_id") String id) {
        return CommerceAccess.owned(access.buyer(auth), s -> shipping.buyer(id, s.merchantId(), s.buyerId()));
    }
}
