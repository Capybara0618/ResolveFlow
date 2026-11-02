package com.resolveflow.commerce.catalog;

import com.resolveflow.shared.error.ApiError;
import com.resolveflow.shared.shopping.ShoppingWire.*;
import java.util.List;
import java.util.UUID;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.*;

/** Anonymous projections only. Never map the internal command surface onto the public prefix. */
@RestController
@RequestMapping("/api/v1/shop")
public class PublicCatalogController {
    private final ShoppingService shopping;
    private final PresentationService presentation;
    private final ProductReviewReadCache reviews;

    public PublicCatalogController(
            ShoppingService shopping, PresentationService presentation, ProductReviewReadCache reviews) {
        this.shopping = shopping;
        this.presentation = presentation;
        this.reviews = reviews;
    }

    @GetMapping("/stores")
    public List<Store> stores() {
        return shopping.stores();
    }

    @GetMapping("/stores/{store_id}")
    public Store store(@PathVariable("store_id") String id) {
        return shopping.store(id);
    }

    @GetMapping("/products")
    public Products products(
            @RequestParam(required = false) String query,
            @RequestParam(required = false) String category,
            @RequestParam(name = "store_id", required = false) String store,
            @RequestParam(required = false) String after,
            @RequestParam(required = false) Integer limit) {
        return shopping.products(query, category, store, after, limit);
    }

    @GetMapping("/products/{product_id}")
    public Product product(@PathVariable("product_id") String id) {
        return shopping.product(id);
    }

    @PostMapping("/quote")
    public Quote quote(@RequestBody QuoteRequest request) {
        return shopping.quote(request);
    }

    @GetMapping("/products/{id}/presentation")
    public com.resolveflow.shared.shopping.PresentationWire.Product productPresentation(@PathVariable String id) {
        return presentation.product(id, null);
    }

    @GetMapping("/stores/{id}/presentation")
    public com.resolveflow.shared.shopping.PresentationWire.Store storePresentation(@PathVariable String id) {
        return presentation.store(id, true);
    }

    @GetMapping("/products/{product_id}/reviews")
    public com.resolveflow.shared.shopping.ProductReviewWire.Page reviews(
            @PathVariable("product_id") String id,
            @RequestParam(required = false) Long before,
            @RequestParam(required = false) Integer limit) {
        return reviews.read(id, before, limit);
    }

    @ExceptionHandler(ShoppingService.Refused.class)
    public ResponseEntity<ApiError> refused(ShoppingService.Refused error) {
        return ResponseEntity.status(error.status).body(error(error.code, error.getMessage(), false));
    }

    @ExceptionHandler(IllegalArgumentException.class)
    public ResponseEntity<ApiError> invalid(IllegalArgumentException error) {
        return ResponseEntity.badRequest().body(error("INVALID_ARGUMENT", error.getMessage(), false));
    }

    @ExceptionHandler(ProductReviewReadCache.ReadBusy.class)
    public ResponseEntity<ApiError> busy() {
        return ResponseEntity.status(503).body(error("SERVICE_UNAVAILABLE", "评价读取繁忙，请稍后重试", true));
    }

    private static ApiError error(String code, String message, boolean retryable) {
        return ApiError.of(code, message, retryable, UUID.randomUUID().toString());
    }
}
