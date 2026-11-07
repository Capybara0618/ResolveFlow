package com.resolveflow.commerce.publicapi;

import com.resolveflow.commerce.catalog.*;
import com.resolveflow.shared.shopping.CartWire.*;
import com.resolveflow.shared.shopping.MultiCheckoutWire;
import org.springframework.web.bind.annotation.*;

@RestController
@RequestMapping("/api/v1/shop/cart")
public class PublicCartController {
    private final CommerceAccess access;
    private final CartService carts;
    private final MultiCheckoutService checkout;

    public PublicCartController(CommerceAccess access, CartService carts, MultiCheckoutService checkout) {
        this.access = access;
        this.carts = carts;
        this.checkout = checkout;
    }

    @GetMapping
    public Cart read(@RequestHeader(name = "Authorization", required = false) String auth) {
        var actor = access.buyer(auth);
        return new Cart(actor.bindings().stream()
                .map(s -> carts.read(s.merchantId(), s.buyerId()))
                .toList());
    }

    @PostMapping("/{store_id}/items")
    public Receipt write(
            @RequestHeader(name = "Authorization", required = false) String auth,
            @RequestHeader(name = "Idempotency-Key", required = false) String key,
            @PathVariable("store_id") String store,
            @RequestBody Request request) {
        var s = CommerceAccess.binding(access.buyer(auth), store);
        return carts.write(new Command(s.merchantId(), s.buyerId(), CommerceAccess.key(key), request));
    }

    @PostMapping("/{store_id}/quote")
    public MultiCheckoutWire.Quote quote(
            @RequestHeader(name = "Authorization", required = false) String auth,
            @PathVariable("store_id") String store,
            @RequestBody MultiCheckoutWire.QuoteRequest request) {
        var s = CommerceAccess.binding(access.buyer(auth), store);
        return checkout.quote(new MultiCheckoutWire.QuoteCommand(s.merchantId(), s.buyerId(), request));
    }

    @PostMapping("/{store_id}/drafts")
    public com.resolveflow.shared.shopping.CheckoutWire.Purchase create(
            @RequestHeader(name = "Authorization", required = false) String auth,
            @RequestHeader(name = "Idempotency-Key", required = false) String key,
            @PathVariable("store_id") String store,
            @RequestBody MultiCheckoutWire.Request request) {
        var s = CommerceAccess.binding(access.buyer(auth), store);
        CommerceAccess.key(key);
        if (request.shipping() == null) throw new ShoppingService.Refused(400, "ADDRESS_REQUIRED", "请选择收货地址");
        try {
            return checkout.create(new MultiCheckoutWire.Command(s.merchantId(), s.buyerId(), key, request));
        } catch (ShoppingService.Refused e) {
            if (!e.code.equals("SHIPPING_NOT_CAPTURED")) throw e;
        }
        // Both transactions finish before this account call; a replay needs no address reread.
        var snapshot = access.shipping(auth, request.shipping());
        return checkout.create(new MultiCheckoutWire.Command(s.merchantId(), s.buyerId(), key, request, snapshot));
    }
}
