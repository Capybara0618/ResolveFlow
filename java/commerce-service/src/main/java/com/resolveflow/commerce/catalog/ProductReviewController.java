package com.resolveflow.commerce.catalog;

import com.resolveflow.shared.error.ApiError;
import com.resolveflow.shared.shopping.ProductReviewWire.*;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.*;

@RestController
public class ProductReviewController {
    private final ProductReviewService reviews;

    public ProductReviewController(ProductReviewService reviews) {
        this.reviews = reviews;
    }

    @GetMapping("/internal/v1/shop/products/{product_id}/reviews")
    public Page list(
            @PathVariable("product_id") String id,
            @RequestParam(required = false) Long before,
            @RequestParam(required = false) Integer limit) {
        return reviews.publicPage(id, before, limit);
    }

    @GetMapping("/internal/v1/shop/orders/lines/{line_id}/review")
    public Own own(
            @PathVariable("line_id") String id,
            @RequestParam("merchant_id") String merchant,
            @RequestParam("customer_id") String customer) {
        return reviews.own(id, merchant, customer);
    }

    @PostMapping("/internal/v1/shop/orders/lines/{line_id}/review")
    public Review save(@PathVariable("line_id") String id, @RequestBody Command command) {
        return reviews.save(id, command);
    }

    @GetMapping("/internal/v1/merchant/reviews")
    public Page merchant(
            @RequestParam("merchant_id") String merchant,
            @RequestParam(required = false) Long before,
            @RequestParam(required = false) Integer limit) {
        return reviews.merchantPage(merchant, before, limit);
    }

    @PostMapping("/internal/v1/merchant/reviews/{review_id}/reply")
    public Review reply(@PathVariable("review_id") long id, @RequestBody ReplyCommand command) {
        return reviews.reply(id, command);
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
