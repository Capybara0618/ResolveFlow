package com.resolveflow.caseservice.shopping;

import com.resolveflow.caseservice.auth.BuyerScopes;
import com.resolveflow.caseservice.order.RequestPrincipalResolver;
import com.resolveflow.shared.error.ApiError;
import com.resolveflow.shared.security.AuthenticatedPrincipal;
import com.resolveflow.shared.shopping.ShoppingWire.*;
import java.util.List;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.*;

@RestController
@RequestMapping("/api/v1/shop")
public class ShopController {
    private final CommerceShoppingClient commerce;
    private final RequestPrincipalResolver principals;
    private final BuyerScopes scopes;
    private final com.resolveflow.caseservice.auth.AccountService accounts;

    public ShopController(
            CommerceShoppingClient commerce,
            RequestPrincipalResolver principals,
            BuyerScopes scopes,
            com.resolveflow.caseservice.auth.AccountService accounts) {
        this.commerce = commerce;
        this.principals = principals;
        this.scopes = scopes;
        this.accounts = accounts;
    }

    @GetMapping("/stores")
    public List<Store> stores() {
        return commerce.stores();
    }

    @GetMapping("/stores/{store_id}")
    public Store store(@PathVariable("store_id") String id) {
        return commerce.store(id);
    }

    @GetMapping("/products")
    public Products products(
            @RequestParam(required = false) String query,
            @RequestParam(required = false) String category,
            @RequestParam(name = "store_id", required = false) String store,
            @RequestParam(required = false) String after,
            @RequestParam(required = false) Integer limit) {
        return commerce.products(query, category, store, after, limit);
    }

    @GetMapping("/products/{product_id}")
    public Product product(@PathVariable("product_id") String id) {
        return commerce.product(id);
    }

    @PostMapping("/quote")
    public Quote quote(@RequestBody QuoteRequest request) {
        return commerce.quote(request);
    }

    private AuthenticatedPrincipal buyer(String authorization) {
        var p = principals.resolve(authorization);
        if (!p.isPlatformBuyer()) throw new CommerceShoppingClient.Refused(403, "FORBIDDEN_SCOPE", "请使用平台买家账号购买商品");
        return p;
    }

    @PostMapping("/drafts")
    public Draft create(
            @RequestHeader(name = "Authorization", required = false) String authorization,
            @RequestHeader(name = "Idempotency-Key", required = false) String key,
            @RequestBody DraftRequest request) {
        var p = buyer(authorization);
        if (request.shipping() == null) throw new CommerceShoppingClient.Refused(400, "ADDRESS_REQUIRED", "请选择收货地址");
        if (key == null || !key.matches("[A-Za-z0-9_-]{1,128}"))
            throw new CommerceShoppingClient.Refused(400, "INVALID_ARGUMENT", "缺少有效的请求标识");
        // Only trusted bindings become private commands; Commerce matches the actual SKU store.
        var owned = scopes.list(p);
        // Replays remain possible even if the public SKU is subsequently delisted.
        // The command probes only trusted scopes and Commerce never creates for a different store.
        for (var s : owned) {
            try {
                return commerce.create(new DraftCommand(s.merchantId(), s.customerId(), key, request));
            } catch (CommerceShoppingClient.Refused e) {
                if (e.code.equals("SHIPPING_NOT_CAPTURED")) {
                    var snapshot = accounts.shipping(principals.session(authorization), request.shipping());
                    try {
                        return commerce.create(
                                new DraftCommand(s.merchantId(), s.customerId(), key, request, snapshot));
                    } catch (CommerceShoppingClient.Refused retry) {
                        if (retry.status != 404) throw retry;
                    }
                } else if (e.status != 404) throw e;
            }
        }
        throw new CommerceShoppingClient.Refused(404, "NOT_FOUND", "商品或订单不存在");
    }

    @GetMapping("/drafts/{draft_id}")
    public Draft read(
            @RequestHeader(name = "Authorization", required = false) String authorization,
            @PathVariable("draft_id") String id) {
        var p = buyer(authorization);
        for (var s : scopes.list(p)) {
            try {
                return commerce.read(id, s.merchantId(), s.customerId());
            } catch (CommerceShoppingClient.Refused e) {
                if (e.status != 404) throw e;
            }
        }
        throw new CommerceShoppingClient.Refused(404, "NOT_FOUND", "商品或订单不存在");
    }

    @ExceptionHandler(CommerceShoppingClient.Refused.class)
    public ResponseEntity<ApiError> refused(CommerceShoppingClient.Refused error) {
        return ResponseEntity.status(error.status)
                .body(ApiError.of(
                        error.code,
                        error.getMessage(),
                        false,
                        java.util.UUID.randomUUID().toString()));
    }
}
