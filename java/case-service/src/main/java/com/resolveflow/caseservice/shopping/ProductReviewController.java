package com.resolveflow.caseservice.shopping;

import com.resolveflow.caseservice.auth.BuyerScopes;
import com.resolveflow.caseservice.order.RequestPrincipalResolver;
import com.resolveflow.shared.error.ApiError;
import com.resolveflow.shared.security.AuthenticatedPrincipal;
import com.resolveflow.shared.security.Role;
import com.resolveflow.shared.shopping.ProductReviewWire.*;
import java.util.function.Function;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.*;

@RestController
public class ProductReviewController {
    private final CommerceShoppingClient commerce;
    private final RequestPrincipalResolver principals;
    private final BuyerScopes scopes;

    public ProductReviewController(
            CommerceShoppingClient commerce, RequestPrincipalResolver principals, BuyerScopes scopes) {
        this.commerce = commerce;
        this.principals = principals;
        this.scopes = scopes;
    }

    private AuthenticatedPrincipal buyer(String auth) {
        var p = principals.resolve(auth);
        if (!p.isPlatformBuyer()) throw new CommerceShoppingClient.Refused(403, "FORBIDDEN_SCOPE", "请使用平台买家账号评价本人商品");
        return p;
    }

    private AuthenticatedPrincipal merchant(String auth) {
        var p = principals.resolve(auth);
        if (p.role() != Role.MERCHANT_ADMIN)
            throw new CommerceShoppingClient.Refused(403, "FORBIDDEN_SCOPE", "商品评价管理仅供本商家使用");
        return p;
    }

    private <T> T owned(AuthenticatedPrincipal p, Function<BuyerScopes.Scope, T> read) {
        for (var scope : scopes.list(p))
            try {
                return read.apply(scope);
            } catch (CommerceShoppingClient.Refused e) {
                if (e.status != 404) throw e;
            }
        throw new CommerceShoppingClient.Refused(404, "NOT_FOUND", "评价或订单行不存在");
    }

    @GetMapping("/api/v1/shop/products/{product_id}/reviews")
    public Page list(
            @PathVariable("product_id") String id,
            @RequestParam(required = false) Long before,
            @RequestParam(required = false) Integer limit) {
        return commerce.productReviews(id, before, limit);
    }

    @GetMapping("/api/v1/shop/orders/lines/{line_id}/review")
    public Own own(
            @RequestHeader(name = "Authorization", required = false) String auth, @PathVariable("line_id") String id) {
        return owned(buyer(auth), s -> commerce.ownReview(id, s.merchantId(), s.customerId()));
    }

    @PostMapping("/api/v1/shop/orders/lines/{line_id}/review")
    public Review save(
            @RequestHeader(name = "Authorization", required = false) String auth,
            @PathVariable("line_id") String id,
            @RequestBody Write request) {
        return owned(buyer(auth), s -> commerce.saveReview(id, new Command(s.merchantId(), s.customerId(), request)));
    }

    @GetMapping("/api/v1/merchant/reviews")
    public Page merchant(
            @RequestHeader(name = "Authorization", required = false) String auth,
            @RequestParam(required = false) Long before,
            @RequestParam(required = false) Integer limit) {
        return commerce.merchantReviews(merchant(auth).merchantId(), before, limit);
    }

    @PostMapping("/api/v1/merchant/reviews/{review_id}/reply")
    public Review reply(
            @RequestHeader(name = "Authorization", required = false) String auth,
            @PathVariable("review_id") long id,
            @RequestBody Reply request) {
        return commerce.replyReview(id, new ReplyCommand(merchant(auth).merchantId(), request));
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
