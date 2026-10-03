package com.resolveflow.commerce.catalog;

import com.resolveflow.shared.error.ApiError;
import com.resolveflow.shared.shopping.FulfillmentWire.*;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.*;

@RestController
public class MerchantTradeController {
    private final MerchantTradeService trades;

    public MerchantTradeController(MerchantTradeService trades) {
        this.trades = trades;
    }

    @GetMapping("/internal/v1/merchant/orders")
    public Trades list(
            @RequestParam("merchant_id") String merchant,
            @RequestParam(required = false) String status,
            @RequestParam(required = false) String cursor,
            @RequestParam(required = false) Integer limit) {
        return trades.list(merchant, status, cursor, limit);
    }

    @GetMapping("/internal/v1/merchant/orders/{order_id}")
    public Trade read(@PathVariable("order_id") String id, @RequestParam("merchant_id") String merchant) {
        return trades.read(id, merchant);
    }

    @PostMapping("/internal/v1/merchant/orders/{order_id}/simulated-shipment")
    public Fulfillment ship(@PathVariable("order_id") String id, @RequestBody ShipCommand command) {
        return trades.ship(id, command);
    }

    @GetMapping("/internal/v1/shop/orders/{order_id}/fulfillment")
    public Fulfillment buyer(
            @PathVariable("order_id") String id,
            @RequestParam("merchant_id") String merchant,
            @RequestParam("customer_id") String customer) {
        return trades.buyer(id, merchant, customer);
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
