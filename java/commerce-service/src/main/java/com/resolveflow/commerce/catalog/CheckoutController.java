package com.resolveflow.commerce.catalog;

import com.resolveflow.shared.error.ApiError;
import com.resolveflow.shared.shopping.CheckoutWire.*;
import com.resolveflow.shared.shopping.ShoppingWire.Draft;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.*;

@RestController
@RequestMapping("/internal/v1/shop")
public class CheckoutController {
    private final CheckoutPayments payments;
    private final PurchaseReads purchases;

    public CheckoutController(CheckoutPayments payments, PurchaseReads purchases) {
        this.payments = payments;
        this.purchases = purchases;
    }

    @PostMapping("/drafts/{draft_id}/payment")
    public Payment pay(@PathVariable("draft_id") String id, @RequestBody PayCommand command) {
        return payments.pay(id, command);
    }

    @GetMapping("/drafts/{draft_id}/payment")
    public Lookup payment(
            @PathVariable("draft_id") String id,
            @RequestParam("merchant_id") String merchant,
            @RequestParam("customer_id") String customer) {
        return new Lookup(payments.inspect(id, merchant, customer));
    }

    @PostMapping("/drafts/{draft_id}/cancel")
    public Draft cancel(@PathVariable("draft_id") String id, @RequestBody ScopeCommand command) {
        return payments.cancel(id, command);
    }

    @GetMapping("/purchases")
    public Purchases list(
            @RequestParam("merchant_id") String merchant,
            @RequestParam("customer_id") String customer,
            @RequestParam(required = false) String status,
            @RequestParam(required = false) String cursor,
            @RequestParam(required = false) Integer limit) {
        return purchases.list(merchant, customer, status, cursor, limit);
    }

    @GetMapping("/purchases/{purchase_id}")
    public Purchase read(
            @PathVariable("purchase_id") String id,
            @RequestParam("merchant_id") String merchant,
            @RequestParam("customer_id") String customer) {
        return purchases.read(id, merchant, customer);
    }

    @ExceptionHandler(ShoppingService.Refused.class)
    public ResponseEntity<ApiError> refused(ShoppingService.Refused e) {
        return ResponseEntity.status(e.status)
                .body(ApiError.of(
                        e.code,
                        e.getMessage(),
                        false,
                        java.util.UUID.randomUUID().toString()));
    }
}
