package com.resolveflow.commerce.catalog;

import com.resolveflow.commerce.CommerceDatabaseTest;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.resttestclient.autoconfigure.AutoConfigureRestTestClient;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.http.MediaType;
import org.springframework.test.web.servlet.client.RestTestClient;

/** Public HTTP is tested against the real Commerce database, without any Case process. */
@AutoConfigureRestTestClient
@SpringBootTest(webEnvironment = SpringBootTest.WebEnvironment.RANDOM_PORT)
class PublicCatalogApiTest extends CommerceDatabaseTest {
    @Autowired
    RestTestClient rest;

    @Test
    void anonymousCatalogUsesTheSameCommerceProjectionAndIgnoresForgedIdentity() {
        rest.get()
                .uri("/api/v1/shop/products?store_id=M-1001&limit=1")
                .header("X-Merchant", "M-1002")
                .header("X-User", "forged")
                .exchange()
                .expectStatus()
                .isOk()
                .expectBody()
                .jsonPath("$.items.length()")
                .isEqualTo(1)
                .jsonPath("$.items[0].store_id")
                .isEqualTo("M-1001");
        rest.get()
                .uri("/api/v1/shop/products/P-1001")
                .exchange()
                .expectStatus()
                .isOk()
                .expectBody()
                .jsonPath("$.product_id")
                .isEqualTo("P-1001");
        rest.get().uri("/api/v1/shop/stores").exchange().expectStatus().isOk();
        rest.get().uri("/api/v1/shop/stores/M-1001").exchange().expectStatus().isOk();
    }

    @Test
    void anonymousPresentationAndReviewsDoNotNeedCaseOrExposePrivateData() {
        rest.get()
                .uri("/api/v1/shop/products/P-1001/presentation")
                .exchange()
                .expectStatus()
                .isOk();
        rest.get()
                .uri("/api/v1/shop/stores/M-1001/presentation")
                .exchange()
                .expectStatus()
                .isOk();
        rest.get()
                .uri("/api/v1/shop/products/P-1001/reviews?limit=5")
                .exchange()
                .expectStatus()
                .isOk()
                .expectBody()
                .jsonPath("$.summary.stars.length()")
                .isEqualTo(5);
    }

    @Test
    void quoteIsReadOnlyAndRejectsIdentityAndMoneyInjection() {
        rest.post()
                .uri("/api/v1/shop/quote")
                .contentType(MediaType.APPLICATION_JSON)
                .body("{\"sku_id\":\"SKU-1001-BLACK\",\"quantity\":1}")
                .exchange()
                .expectStatus()
                .isOk()
                .expectBody()
                .jsonPath("$.total_amount")
                .isEqualTo(32900);
        rest.post()
                .uri("/api/v1/shop/quote")
                .contentType(MediaType.APPLICATION_JSON)
                .body("{\"sku_id\":\"SKU-1001-BLACK\",\"quantity\":1,\"total_amount\":1}")
                .exchange()
                .expectStatus()
                .isBadRequest();
        rest.post()
                .uri("/api/v1/shop/quote")
                .contentType(MediaType.APPLICATION_JSON)
                .body("{\"sku_id\":\"SKU-1001-BLACK\",\"quantity\":0}")
                .exchange()
                .expectStatus()
                .isBadRequest()
                .expectBody()
                .jsonPath("$.code")
                .isEqualTo("INVALID_ARGUMENT");
    }

    @Test
    void missingProductsRetainNotFoundAndPrivateInternalRoutesStillRequireServiceAuth() {
        rest.get()
                .uri("/api/v1/shop/products/missing")
                .exchange()
                .expectStatus()
                .isNotFound()
                .expectBody()
                .jsonPath("$.code")
                .isEqualTo("NOT_FOUND");
        rest.get().uri("/internal/v1/shop/products").exchange().expectStatus().isUnauthorized();
        rest.get()
                .uri("/internal/v1/shop/cart/M-1001?buyer_id=OTHER")
                .exchange()
                .expectStatus()
                .isUnauthorized();
        rest.post()
                .uri("/api/v1/shop/drafts")
                .contentType(MediaType.APPLICATION_JSON)
                .body("{}")
                .exchange()
                .expectStatus()
                .isUnauthorized();
        rest.post()
                .uri("/api/v1/shop/products/P-1001/presentation")
                .contentType(MediaType.APPLICATION_JSON)
                .body("{}")
                .exchange()
                .expectStatus()
                .is4xxClientError();
    }
}
