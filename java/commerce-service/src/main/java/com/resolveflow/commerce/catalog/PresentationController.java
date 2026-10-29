package com.resolveflow.commerce.catalog;

import com.resolveflow.shared.error.ApiError;
import com.resolveflow.shared.shopping.PresentationWire.*;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.*;

@RestController
public class PresentationController {
    private final PresentationService service;

    public PresentationController(PresentationService service) {
        this.service = service;
    }

    @GetMapping("/internal/v1/shop/presentation/products/{id}")
    public Product product(@PathVariable String id) {
        return service.product(id, null);
    }

    @GetMapping("/internal/v1/shop/presentation/stores/{id}")
    public Store store(@PathVariable String id) {
        return service.store(id, true);
    }

    @GetMapping("/internal/v1/shop/presentation/media/{id}")
    public Published published(@PathVariable String id) {
        return service.published(id);
    }

    @GetMapping("/internal/v1/catalog-management/presentation/products/{id}")
    public Product managed(@PathVariable String id, @RequestParam String merchant_id) {
        return service.product(id, merchant_id);
    }

    @PostMapping("/internal/v1/catalog-management/presentation/products/{id}")
    public Product save(@PathVariable String id, @RequestBody ProductCommand body) {
        return service.saveProduct(id, body);
    }

    @GetMapping("/internal/v1/catalog-management/presentation/store")
    public Store managedStore(@RequestParam String merchant_id) {
        return service.store(merchant_id, false);
    }

    @PostMapping("/internal/v1/catalog-management/presentation/store")
    public Store saveStore(@RequestBody StoreCommand body) {
        return service.saveStore(body);
    }

    @ExceptionHandler(ShoppingService.Refused.class)
    public ResponseEntity<ApiError> refused(ShoppingService.Refused e) {
        return ResponseEntity.status(e.status).body(ApiError.of(e.code, e.getMessage(), false, "presentation"));
    }

    @ExceptionHandler(IllegalArgumentException.class)
    public ResponseEntity<ApiError> invalid(IllegalArgumentException e) {
        return ResponseEntity.badRequest().body(ApiError.of("INVALID_ARGUMENT", e.getMessage(), false, "presentation"));
    }
}
