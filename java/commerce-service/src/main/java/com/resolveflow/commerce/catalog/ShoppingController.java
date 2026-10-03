package com.resolveflow.commerce.catalog;

import com.resolveflow.shared.error.ApiError;
import com.resolveflow.shared.shopping.ShoppingWire.*;
import java.util.List;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.*;

@RestController
@RequestMapping("/internal/v1/shop")
public class ShoppingController {
    private final ShoppingService service;

    public ShoppingController(ShoppingService service) {
        this.service = service;
    }

    @GetMapping("/stores")
    public List<Store> stores() {
        return service.stores();
    }

    @GetMapping("/stores/{store_id}")
    public Store store(@PathVariable("store_id") String id) {
        return service.store(id);
    }

    @GetMapping("/products")
    public Products products(
            @RequestParam(required = false) String query,
            @RequestParam(required = false) String category,
            @RequestParam(name = "store_id", required = false) String store,
            @RequestParam(required = false) String after,
            @RequestParam(required = false) Integer limit) {
        return service.products(query, category, store, after, limit);
    }

    @GetMapping("/products/{product_id}")
    public Product product(@PathVariable("product_id") String id) {
        return service.product(id);
    }

    @PostMapping("/quote")
    public Quote quote(@RequestBody QuoteRequest request) {
        return service.quote(request);
    }

    @PostMapping("/drafts")
    public Draft create(@RequestBody DraftCommand command) {
        return service.create(command);
    }

    @GetMapping("/drafts/{draft_id}")
    public Draft read(
            @PathVariable("draft_id") String id,
            @RequestParam("merchant_id") String merchant,
            @RequestParam("customer_id") String customer) {
        return service.read(id, merchant, customer);
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
