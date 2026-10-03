package com.resolveflow.caseservice.shopping;

import com.resolveflow.caseservice.auth.BuyerScopes;
import com.resolveflow.caseservice.order.RequestPrincipalResolver;
import com.resolveflow.shared.error.ApiError;
import com.resolveflow.shared.security.AuthenticatedPrincipal;
import com.resolveflow.shared.shopping.CartWire.*;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.*;

@RestController
@RequestMapping("/api/v1/shop/cart")
public class CartController {
    private final CommerceShoppingClient commerce;
    private final BuyerScopes scopes;
    private final RequestPrincipalResolver principals;

    public CartController(CommerceShoppingClient commerce, BuyerScopes scopes, RequestPrincipalResolver principals) {
        this.commerce = commerce;
        this.scopes = scopes;
        this.principals = principals;
    }

    private AuthenticatedPrincipal buyer(String authorization) {
        var p = principals.resolve(authorization);
        if (!p.isPlatformBuyer()) throw new CommerceShoppingClient.Refused(403, "FORBIDDEN_SCOPE", "请使用平台买家账号管理购物车");
        return p;
    }

    @GetMapping
    public Cart read(@RequestHeader(name = "Authorization", required = false) String authorization) {
        var p = buyer(authorization);
        // Fail the complete read on a store outage; never imply the other store's cart is empty.
        return new Cart(scopes.list(p).stream()
                .map(s -> commerce.cart(s.merchantId(), s.customerId()))
                .toList());
    }

    @PostMapping("/{store_id}/items")
    public Receipt write(
            @RequestHeader(name = "Authorization", required = false) String authorization,
            @RequestHeader(name = "Idempotency-Key", required = false) String key,
            @PathVariable("store_id") String store,
            @RequestBody Request request) {
        var p = buyer(authorization);
        if (key == null || !key.matches("[A-Za-z0-9_-]{1,128}"))
            throw new CommerceShoppingClient.Refused(400, "INVALID_ARGUMENT", "缺少有效请求标识");
        var s = scopes.list(p).stream()
                .filter(v -> v.merchantId().equals(store))
                .findFirst()
                .orElseThrow(() -> new CommerceShoppingClient.Refused(404, "NOT_FOUND", "店铺不存在"));
        return commerce.cartWrite(store, new Command(s.merchantId(), s.customerId(), key, request));
    }

    private BuyerScopes.Scope store(String authorization, String store) {
        return scopes.list(buyer(authorization)).stream()
                .filter(s -> s.merchantId().equals(store))
                .findFirst()
                .orElseThrow(() -> new CommerceShoppingClient.Refused(404, "NOT_FOUND", "店铺不存在"));
    }

    @PostMapping("/{store_id}/quote")
    public com.resolveflow.shared.shopping.MultiCheckoutWire.Quote quote(
            @RequestHeader(name = "Authorization", required = false) String authorization,
            @PathVariable("store_id") String store,
            @RequestBody com.resolveflow.shared.shopping.MultiCheckoutWire.QuoteRequest request) {
        var s = store(authorization, store);
        return commerce.cartQuote(
                store,
                new com.resolveflow.shared.shopping.MultiCheckoutWire.QuoteCommand(
                        s.merchantId(), s.customerId(), request));
    }

    @PostMapping("/{store_id}/drafts")
    public com.resolveflow.shared.shopping.CheckoutWire.Purchase create(
            @RequestHeader(name = "Authorization", required = false) String authorization,
            @RequestHeader(name = "Idempotency-Key", required = false) String key,
            @PathVariable("store_id") String store,
            @RequestBody com.resolveflow.shared.shopping.MultiCheckoutWire.Request request) {
        var s = store(authorization, store);
        if (key == null || !key.matches("[A-Za-z0-9_-]{1,128}"))
            throw new CommerceShoppingClient.Refused(400, "INVALID_ARGUMENT", "缺少有效请求标识");
        return commerce.cartDraft(
                store,
                new com.resolveflow.shared.shopping.MultiCheckoutWire.Command(
                        s.merchantId(), s.customerId(), key, request));
    }

    @ExceptionHandler(CommerceShoppingClient.Refused.class)
    public ResponseEntity<ApiError> refused(CommerceShoppingClient.Refused e) {
        return ResponseEntity.status(e.status)
                .body(ApiError.of(
                        e.code,
                        e.getMessage(),
                        false,
                        java.util.UUID.randomUUID().toString()));
    }
}
