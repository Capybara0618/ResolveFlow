package com.resolveflow.commerce.catalog;

import com.resolveflow.shared.error.ApiError;
import com.resolveflow.shared.shopping.ManagementWire.*;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.*;

@RestController
@RequestMapping("/internal/v1/catalog-management")
public class CatalogManagementController {
    private final CatalogManagementService service;

    public CatalogManagementController(CatalogManagementService service) {
        this.service = service;
    }

    @PostMapping("/stores")
    public StoreSync sync(@RequestBody StoreSync request) {
        return service.sync(request);
    }

    @GetMapping("/products")
    public Products list(
            @RequestParam("merchant_id") String merchant,
            @RequestParam(required = false) String after,
            @RequestParam(required = false) Integer limit) {
        return service.list(merchant, after, limit);
    }

    @GetMapping("/products/{id}")
    public Product read(@PathVariable String id, @RequestParam("merchant_id") String merchant) {
        return service.read(merchant, id);
    }

    @PostMapping("/products")
    public ResponseEntity<Product> create(@RequestBody ProductCommand request) {
        return ResponseEntity.status(201).body(service.save(null, request));
    }

    @PostMapping("/products/{id}")
    public Product update(@PathVariable String id, @RequestBody ProductCommand request) {
        return service.save(id, request);
    }

    @ExceptionHandler(ShoppingService.Refused.class)
    public ResponseEntity<ApiError> refused(ShoppingService.Refused error) {
        return ResponseEntity.status(error.status)
                .body(ApiError.of(
                        error.code,
                        error.getMessage(),
                        false,
                        java.util.UUID.randomUUID().toString()));
    }
}
