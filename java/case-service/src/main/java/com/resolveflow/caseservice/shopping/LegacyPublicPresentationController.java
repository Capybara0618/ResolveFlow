package com.resolveflow.caseservice.shopping;

import com.resolveflow.shared.error.ApiError;
import com.resolveflow.shared.shopping.PresentationWire.*;
import java.util.UUID;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.*;

/** Historical public facade only; media files and merchant media validation remain separate. */
@ConditionalOnProperty(name = "resolveflow.compat.commerce-facade-enabled", havingValue = "true")
@RestController
public class LegacyPublicPresentationController {
    private final CommerceShoppingClient commerce;

    public LegacyPublicPresentationController(CommerceShoppingClient commerce) {
        this.commerce = commerce;
    }

    @GetMapping("/api/v1/shop/products/{id}/presentation")
    public Product product(@PathVariable String id) {
        return commerce.presentationProduct(id, null);
    }

    @GetMapping("/api/v1/shop/stores/{id}/presentation")
    public Store store(@PathVariable String id) {
        return commerce.presentationStore(id, false);
    }

    @ExceptionHandler(CommerceShoppingClient.Refused.class)
    public ResponseEntity<ApiError> refused(CommerceShoppingClient.Refused error) {
        return ResponseEntity.status(error.status)
                .body(ApiError.of(
                        error.code, error.getMessage(), false, UUID.randomUUID().toString()));
    }
}
