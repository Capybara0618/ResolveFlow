package com.resolveflow.caseservice.shopping;

import com.resolveflow.caseservice.auth.BuyerScopes;
import com.resolveflow.caseservice.order.RequestPrincipalResolver;
import com.resolveflow.shared.error.ApiError;
import com.resolveflow.shared.security.AuthenticatedPrincipal;
import com.resolveflow.shared.security.Role;
import com.resolveflow.shared.shopping.FulfillmentWire.*;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.*;

@org.springframework.boot.autoconfigure.condition.ConditionalOnProperty(
        name = "resolveflow.compat.commerce-facade-enabled",
        havingValue = "true")
@RestController
public class MerchantTradeController {
    private final RequestPrincipalResolver principals;
    private final CommerceShoppingClient commerce;
    private final BuyerScopes scopes;

    public MerchantTradeController(
            RequestPrincipalResolver principals, CommerceShoppingClient commerce, BuyerScopes scopes) {
        this.principals = principals;
        this.commerce = commerce;
        this.scopes = scopes;
    }

    private AuthenticatedPrincipal admin(String auth) {
        var p = principals.resolve(auth);
        if (p.role() != Role.MERCHANT_ADMIN)
            throw new CommerceShoppingClient.Refused(403, "FORBIDDEN_SCOPE", "交易管理仅供本商家管理员使用");
        return p;
    }

    @GetMapping("/api/v1/merchant/orders")
    public Trades list(
            @RequestHeader(name = "Authorization", required = false) String auth,
            @RequestParam(required = false) String status,
            @RequestParam(required = false) String cursor,
            @RequestParam(required = false) Integer limit) {
        return commerce.merchantOrders(admin(auth).merchantId(), status, cursor, limit);
    }

    @GetMapping("/api/v1/merchant/orders/{order_id}")
    public Trade read(
            @RequestHeader(name = "Authorization", required = false) String auth, @PathVariable("order_id") String id) {
        return commerce.merchantOrder(id, admin(auth).merchantId());
    }

    @GetMapping("/api/v1/merchant/orders/{order_id}/shipping")
    public com.resolveflow.shared.shopping.ShippingWire.View shipping(
            @RequestHeader(name = "Authorization", required = false) String auth, @PathVariable("order_id") String id) {
        return commerce.merchantShipping(id, admin(auth).merchantId());
    }

    @PostMapping("/api/v1/merchant/orders/{order_id}/simulated-shipment")
    public Fulfillment ship(
            @RequestHeader(name = "Authorization", required = false) String auth,
            @RequestHeader(name = "Idempotency-Key", required = false) String key,
            @PathVariable("order_id") String id,
            @RequestBody ShipRequest body) {
        var p = admin(auth);
        if (key == null
                || !key.matches("[A-Za-z0-9_-]{1,128}")
                || body.expectedVersion() == null
                || body.expectedVersion() < 1)
            throw new CommerceShoppingClient.Refused(400, "INVALID_ARGUMENT", "需要有效的发货版本和请求标识");
        return commerce.ship(id, new ShipCommand(p.merchantId(), p.subject(), key, body.expectedVersion()));
    }

    @GetMapping("/api/v1/shop/purchases/{purchase_id}/fulfillment")
    public Fulfillment buyer(
            @RequestHeader(name = "Authorization", required = false) String auth,
            @PathVariable("purchase_id") String id) {
        var p = principals.resolve(auth);
        if (!p.isPlatformBuyer()) throw new CommerceShoppingClient.Refused(403, "FORBIDDEN_SCOPE", "请使用平台买家账号查看本人履约");
        for (var s : scopes.list(p))
            try {
                var purchase = commerce.purchase(id, s.merchantId(), s.customerId());
                if (!purchase.status().equals("PAID") || purchase.orderId() == null)
                    throw new CommerceShoppingClient.Refused(404, "NOT_FOUND", "履约记录不存在");
                return commerce.fulfillment(purchase.orderId(), s.merchantId(), s.customerId());
            } catch (CommerceShoppingClient.Refused e) {
                if (e.status != 404) throw e;
            }
        throw new CommerceShoppingClient.Refused(404, "NOT_FOUND", "履约记录不存在");
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
