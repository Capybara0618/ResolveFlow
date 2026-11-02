package com.resolveflow.commerce.publicapi;

import com.resolveflow.commerce.publicapi.PublicOrderWire.*;
import com.resolveflow.commerce.security.IdentityAccessClient;
import org.springframework.web.bind.annotation.*;

@RestController
@RequestMapping("/api/v1/orders")
public class PublicOrderController {
    private final IdentityAccessClient identity;
    private final PublicOrderReads orders;

    public PublicOrderController(IdentityAccessClient identity, PublicOrderReads orders) {
        this.identity = identity;
        this.orders = orders;
    }

    @GetMapping
    public Page list(
            @RequestHeader(name = "Authorization", required = false) String auth,
            @RequestParam(required = false) String cursor,
            @RequestParam(required = false) Integer limit) {
        return orders.list(identity.resolve(auth), cursor, limit);
    }

    @GetMapping("/{order_id}")
    public Page read(
            @RequestHeader(name = "Authorization", required = false) String auth, @PathVariable("order_id") String id) {
        return orders.read(identity.resolve(auth), id);
    }

    @GetMapping("/lines/{line_id}")
    public Summary line(
            @RequestHeader(name = "Authorization", required = false) String auth, @PathVariable("line_id") String id) {
        if (id.isBlank() || id.length() > 64) throw new IllegalArgumentException("商品行编号无效");
        return orders.readLine(identity.resolve(auth), id);
    }
}
