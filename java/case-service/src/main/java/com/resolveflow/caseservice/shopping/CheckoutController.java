package com.resolveflow.caseservice.shopping;

import com.resolveflow.caseservice.auth.BuyerScopes;
import com.resolveflow.caseservice.order.RequestPrincipalResolver;
import com.resolveflow.shared.error.ApiError;
import com.resolveflow.shared.security.AuthenticatedPrincipal;
import com.resolveflow.shared.shopping.CheckoutWire.*;
import com.resolveflow.shared.shopping.ShoppingWire.Draft;
import java.util.function.Function;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.*;

@org.springframework.boot.autoconfigure.condition.ConditionalOnProperty(
        name = "resolveflow.compat.commerce-facade-enabled",
        havingValue = "true")
@RestController
@RequestMapping("/api/v1/shop")
public class CheckoutController {
    private final CommerceShoppingClient commerce;
    private final RequestPrincipalResolver principals;
    private final BuyerScopes scopes;
    private final BuyerPurchaseService purchases;

    @GetMapping("/purchases/{purchase_id}/shipping")
    public com.resolveflow.shared.shopping.ShippingWire.View shipping(
            @RequestHeader(name = "Authorization", required = false) String auth,
            @PathVariable("purchase_id") String id) {
        return owned(buyer(auth), s -> commerce.shipping(id, s.merchantId(), s.customerId()));
    }

    public CheckoutController(
            CommerceShoppingClient commerce,
            RequestPrincipalResolver principals,
            BuyerScopes scopes,
            BuyerPurchaseService purchases) {
        this.commerce = commerce;
        this.principals = principals;
        this.scopes = scopes;
        this.purchases = purchases;
    }

    private AuthenticatedPrincipal buyer(String authorization) {
        var p = principals.resolve(authorization);
        if (!p.isPlatformBuyer()) throw new CommerceShoppingClient.Refused(403, "FORBIDDEN_SCOPE", "请使用平台买家账号查看或支付订单");
        return p;
    }

    private <T> T owned(AuthenticatedPrincipal p, Function<BuyerScopes.Scope, T> call) {
        for (var s : scopes.list(p))
            try {
                return call.apply(s);
            } catch (CommerceShoppingClient.Refused e) {
                if (e.status != 404) throw e;
            }
        throw new CommerceShoppingClient.Refused(404, "NOT_FOUND", "商品或订单不存在");
    }

    @PostMapping("/drafts/{draft_id}/payment")
    public Payment pay(
            @RequestHeader(name = "Authorization", required = false) String auth,
            @RequestHeader(name = "Idempotency-Key", required = false) String key,
            @PathVariable("draft_id") String id,
            @RequestBody EmptyRequest body) {
        var p = buyer(auth);
        if (key == null || !key.matches("[A-Za-z0-9_-]{1,128}"))
            throw new CommerceShoppingClient.Refused(400, "INVALID_ARGUMENT", "需要有效的付款请求标识");
        return owned(p, s -> commerce.pay(id, new PayCommand(s.merchantId(), s.customerId(), key)));
    }

    @GetMapping("/drafts/{draft_id}/payment")
    public Lookup payment(
            @RequestHeader(name = "Authorization", required = false) String auth, @PathVariable("draft_id") String id) {
        return owned(buyer(auth), s -> commerce.payment(id, s.merchantId(), s.customerId()));
    }

    @PostMapping("/drafts/{draft_id}/cancel")
    public Draft cancel(
            @RequestHeader(name = "Authorization", required = false) String auth,
            @PathVariable("draft_id") String id,
            @RequestBody EmptyRequest body) {
        return owned(buyer(auth), s -> commerce.cancel(id, new ScopeCommand(s.merchantId(), s.customerId())));
    }

    @GetMapping("/purchases")
    public Purchases list(
            @RequestHeader(name = "Authorization", required = false) String auth,
            @RequestParam(name = "store_id", required = false) String store,
            @RequestParam(required = false) String status,
            @RequestParam(required = false) String cursor,
            @RequestParam(required = false) Integer limit) {
        return purchases.list(buyer(auth), store, status, cursor, limit);
    }

    @GetMapping("/purchases/{purchase_id}")
    public Purchase read(
            @RequestHeader(name = "Authorization", required = false) String auth,
            @PathVariable("purchase_id") String id) {
        return owned(buyer(auth), s -> commerce.purchase(id, s.merchantId(), s.customerId()));
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
