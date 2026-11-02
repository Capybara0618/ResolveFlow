package com.resolveflow.commerce.publicapi;

import com.resolveflow.commerce.catalog.CatalogManagementService;
import com.resolveflow.shared.shopping.ManagementWire.*;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.*;

@RestController
@RequestMapping("/api/v1/merchant/products")
public class PublicCatalogAdminController {
    private final CommerceAccess access;
    private final CatalogManagementService catalog;

    public PublicCatalogAdminController(CommerceAccess access, CatalogManagementService catalog) {
        this.access = access;
        this.catalog = catalog;
    }

    @GetMapping
    public Products list(
            @RequestHeader(name = "Authorization", required = false) String auth,
            @RequestParam(required = false) String after,
            @RequestParam(required = false) Integer limit) {
        return catalog.list(access.merchant(auth).merchantId(), after, limit);
    }

    @GetMapping("/{id}")
    public Product read(@RequestHeader(name = "Authorization", required = false) String auth, @PathVariable String id) {
        return catalog.read(access.merchant(auth).merchantId(), id);
    }

    @PostMapping
    public ResponseEntity<Product> create(
            @RequestHeader(name = "Authorization", required = false) String auth, @RequestBody ProductWrite body) {
        var p = access.merchant(auth);
        return ResponseEntity.status(201)
                .body(catalog.save(null, new ProductCommand(p.merchantId(), p.subject(), body)));
    }

    @PostMapping("/{id}")
    public Product save(
            @RequestHeader(name = "Authorization", required = false) String auth,
            @PathVariable String id,
            @RequestBody ProductWrite body) {
        var p = access.merchant(auth);
        return catalog.save(id, new ProductCommand(p.merchantId(), p.subject(), body));
    }
}
