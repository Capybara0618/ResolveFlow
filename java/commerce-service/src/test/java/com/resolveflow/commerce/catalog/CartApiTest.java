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
class CartApiTest extends CommerceDatabaseTest {
    @Autowired
    RestTestClient rest;

    @Autowired
    JwtCodec codec;

    @Test
    void evenReadIsPrivateAndAgentCannotAcquireCartCapability() {
        for (var identity : new String[][] {
            {"agent-service", "commerce:read"},
            {"agent-service", "commerce:checkout"},
            {"case-service", "commerce:read"}
        }) {
            String token = codec.issueServiceToken(identity[0], null, null, identity[1], Instant.now());
            rest.get()
                    .uri("/internal/v1/shop/cart/M-1001?customer_id=C-B3001-M1001")
                    .header("Authorization", "Bearer " + token)
                    .exchange()
                    .expectStatus()
                    .isForbidden();
            rest.post()
                    .uri("/internal/v1/shop/cart/M-1001/items")
                    .header("Authorization", "Bearer " + token)
                    .contentType(org.springframework.http.MediaType.APPLICATION_JSON)
                    .body("{}")
                    .exchange()
                    .expectStatus()
                    .isForbidden();
        }
        String caseToken = codec.issueServiceToken("case-service", null, null, "commerce:checkout", Instant.now());
        rest.get()
                .uri("/internal/v1/shop/cart/M-1001?customer_id=C-B3001-M1001")
                .header("Authorization", "Bearer " + caseToken)
                .exchange()
                .expectStatus()
                .isOk()
                .expectBody()
                .jsonPath("$.revision")
                .isEqualTo(0)
                .jsonPath("$.customer_id")
                .doesNotExist();
    }
}
