package com.resolveflow.commerce.catalog;

import com.resolveflow.commerce.CommerceDatabaseTest;
import com.resolveflow.shared.security.JwtCodec;
import java.time.Instant;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.resttestclient.autoconfigure.AutoConfigureRestTestClient;
import org.springframework.test.web.servlet.client.RestTestClient;

@AutoConfigureRestTestClient
@org.springframework.boot.test.context.SpringBootTest(
        webEnvironment = org.springframework.boot.test.context.SpringBootTest.WebEnvironment.RANDOM_PORT)
class ShoppingApiTest extends CommerceDatabaseTest {
    @Autowired
    RestTestClient rest;

    @Autowired
    JwtCodec codec;

    @Test
    void publicCatalogAndAgentCannotWriteDrafts() {
        String read = codec.issueServiceToken("case-service", null, null, "commerce:read", Instant.now());
        rest.get()
                .uri("/internal/v1/shop/products")
                .header("Authorization", "Bearer " + read)
                .exchange()
                .expectStatus()
                .isOk()
                .expectBody()
                .jsonPath("$.items.length()")
                .isEqualTo(6);
        String agent = codec.issueServiceToken("agent-service", null, null, "commerce:read policy:read", Instant.now());
        rest.post()
                .uri("/internal/v1/shop/drafts")
                .header("Authorization", "Bearer " + agent)
                .contentType(org.springframework.http.MediaType.APPLICATION_JSON)
                .body("{}")
                .exchange()
                .expectStatus()
                .isForbidden();
    }
}
