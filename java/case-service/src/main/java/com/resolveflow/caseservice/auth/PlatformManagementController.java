package com.resolveflow.caseservice.auth;

import com.resolveflow.caseservice.auth.PlatformManagementService.*;
import com.resolveflow.caseservice.order.RequestPrincipalResolver;
import com.resolveflow.caseservice.shopping.CommerceShoppingClient;
import com.resolveflow.shared.error.ApiError;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.*;

@RestController
@RequestMapping("/api/v1/platform")
public class PlatformManagementController {
    private final PlatformManagementService service;
    private final RequestPrincipalResolver principals;

    public PlatformManagementController(PlatformManagementService service, RequestPrincipalResolver principals) {
        this.service = service;
        this.principals = principals;
    }

    @GetMapping("/merchants")
    public Merchants merchants(
            @RequestHeader(name = "Authorization", required = false) String auth,
            @RequestParam(required = false) String after,
            @RequestParam(defaultValue = "") String query,
            @RequestParam(defaultValue = "20") int limit) {
        return service.merchants(principals.session(auth), after, query, limit);
    }

    @PostMapping("/merchants")
    public ResponseEntity<Merchant> createMerchant(
            @RequestHeader(name = "Authorization", required = false) String auth, @RequestBody MerchantCreate r) {
        return ResponseEntity.status(201).body(service.createMerchant(principals.session(auth), r));
    }

    @PostMapping("/merchants/{id}")
    public Merchant updateMerchant(
            @RequestHeader(name = "Authorization", required = false) String auth,
            @PathVariable String id,
            @RequestBody MerchantUpdate r) {
        return service.updateMerchant(principals.session(auth), id, r);
    }

    @PostMapping("/merchants/{id}/sync")
    public Merchant sync(
            @RequestHeader(name = "Authorization", required = false) String auth, @PathVariable String id) {
        return service.synchronize(principals.session(auth), id);
    }

    @GetMapping("/buyers")
    public Buyers buyers(
            @RequestHeader(name = "Authorization", required = false) String auth,
            @RequestParam(required = false) String after,
            @RequestParam(defaultValue = "") String query,
            @RequestParam(defaultValue = "20") int limit) {
        return service.buyers(principals.session(auth), after, query, limit);
    }

    @PostMapping("/buyers")
    public ResponseEntity<Buyer> createBuyer(
            @RequestHeader(name = "Authorization", required = false) String auth, @RequestBody BuyerCreate r) {
        return ResponseEntity.status(201).body(service.createBuyer(principals.session(auth), r));
    }

    @PostMapping("/buyers/{id}")
    public Buyer updateBuyer(
            @RequestHeader(name = "Authorization", required = false) String auth,
            @PathVariable String id,
            @RequestBody BuyerUpdate r) {
        return service.updateBuyer(principals.session(auth), id, r);
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
