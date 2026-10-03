package com.resolveflow.commerce.catalog;

import com.resolveflow.shared.error.ApiError;
import com.resolveflow.shared.shopping.CartWire.*;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.*;

@RestController
@RequestMapping("/internal/v1/shop/cart")
public class CartController {
    private final CartService cart;

    public CartController(CartService cart) {
        this.cart = cart;
    }

    @GetMapping("/{store_id}")
    public Group read(@PathVariable("store_id") String store, @RequestParam("customer_id") String customer) {
        return cart.read(store, customer);
    }

    @PostMapping("/{store_id}/items")
    public Receipt write(@PathVariable("store_id") String store, @RequestBody Command command) {
        if (command == null || !store.equals(command.merchantId())) throw new IllegalArgumentException("购物车归属不一致");
        return cart.write(command);
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
