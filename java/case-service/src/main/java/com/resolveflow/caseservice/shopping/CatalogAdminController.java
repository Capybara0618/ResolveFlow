package com.resolveflow.caseservice.shopping;

import com.resolveflow.caseservice.order.RequestPrincipalResolver;
import com.resolveflow.shared.error.ApiError;
import com.resolveflow.shared.security.AuthenticatedPrincipal;
import com.resolveflow.shared.security.Role;
import com.resolveflow.shared.shopping.ManagementWire.*;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.*;

@RestController
@RequestMapping("/api/v1/merchant/products")
public class CatalogAdminController {
    private final RequestPrincipalResolver principals;
    private final CommerceShoppingClient commerce;

    public CatalogAdminController(RequestPrincipalResolver principals, CommerceShoppingClient commerce) {
        this.principals = principals;
        this.commerce = commerce;
    }

    private AuthenticatedPrincipal admin(String auth) {
        var p = principals.resolve(auth);
        if (p.role() != Role.MERCHANT_ADMIN)
            throw new CommerceShoppingClient.Refused(403, "FORBIDDEN_SCOPE", "仅本商家管理员可维护商品");
        return p;
    }

    @GetMapping
    public Products list(
            @RequestHeader(name = "Authorization", required = false) String auth,
            @RequestParam(required = false) String after,
            @RequestParam(required = false) Integer limit) {
        return commerce.managedProducts(admin(auth).merchantId(), after, limit);
    }

    @GetMapping("/{id}")
    public Product read(@RequestHeader(name = "Authorization", required = false) String auth, @PathVariable String id) {
        return commerce.managedProduct(admin(auth).merchantId(), id);
    }

    @PostMapping
    public ResponseEntity<Product> create(
            @RequestHeader(name = "Authorization", required = false) String auth, @RequestBody ProductWrite request) {
        var p = admin(auth);
        return ResponseEntity.status(201)
                .body(commerce.saveProduct(null, new ProductCommand(p.merchantId(), p.subject(), request)));
    }

    @PostMapping("/{id}")
    public Product update(
            @RequestHeader(name = "Authorization", required = false) String auth,
            @PathVariable String id,
            @RequestBody ProductWrite request) {
        var p = admin(auth);
        return commerce.saveProduct(id, new ProductCommand(p.merchantId(), p.subject(), request));
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
