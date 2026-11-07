package com.resolveflow.commerce.catalog;

import com.resolveflow.commerce.CommerceDatabaseTest;
import com.resolveflow.shared.security.JwtCodec;
import java.time.Instant;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.resttestclient.autoconfigure.AutoConfigureRestTestClient;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.http.MediaType;
import org.springframework.test.web.servlet.client.RestTestClient;

@AutoConfigureRestTestClient
@SpringBootTest(webEnvironment = SpringBootTest.WebEnvironment.RANDOM_PORT)
class CheckoutApiTest extends CommerceDatabaseTest {
    @Autowired
    RestTestClient rest;

    @Autowired
    JwtCodec codec;

    private String token(String subject, String scope) {
        return "Bearer " + codec.issueServiceToken(subject, null, null, scope, Instant.now());
    }

    @Test
    void checkoutPrivateReadsAndPaymentWritesRequireCaseDeploymentNotAgentOrReadToken() {
        for (var token : java.util.List.of(
                token("agent-service", "commerce:read policy:read"),
                token("agent-service", "commerce:checkout"),
                token("case-service", "commerce:read"))) {
            rest.get()
                    .uri("/internal/v1/shop/purchases?merchant_id=M-1001&buyer_id=C-1001")
                    .header("Authorization", token)
                    .exchange()
                    .expectStatus()
                    .isForbidden();
            rest.post()
                    .uri("/internal/v1/shop/drafts/not-owned/payment")
                    .header("Authorization", token)
                    .contentType(MediaType.APPLICATION_JSON)
                    .body("{}")
                    .exchange()
                    .expectStatus()
                    .isForbidden();
        }
        rest.get()
                .uri("/internal/v1/shop/purchases?merchant_id=M-1001&buyer_id=C-1001")
                .header("Authorization", token("case-service", "commerce:checkout"))
                .exchange()
                .expectStatus()
                .isOk();
    }

    @Test
    void internalPaymentNeverAcceptsClientAmountOrWrongCompositeScope() {
        String token = token("case-service", "commerce:checkout");
        rest.post()
                .uri("/internal/v1/shop/drafts/foreign/payment")
                .header("Authorization", token)
                .contentType(MediaType.APPLICATION_JSON)
                .body(
                        "{\"merchant_id\":\"M-1001\",\"buyer_id\":\"other\",\"idempotency_key\":\"key\",\"total_amount\":1}")
                .exchange()
                .expectStatus()
                .isBadRequest();
        rest.post()
                .uri("/internal/v1/shop/drafts/foreign/payment")
                .header("Authorization", token)
                .contentType(MediaType.APPLICATION_JSON)
                .body("{\"merchant_id\":\"M-1001\",\"buyer_id\":\"other\",\"idempotency_key\":\"key\"}")
                .exchange()
                .expectStatus()
                .isNotFound();
        rest.get()
                .uri("/internal/v1/shop/drafts/foreign/payment?merchant_id=M-1001&buyer_id=other")
                .header("Authorization", token)
                .exchange()
                .expectStatus()
                .isNotFound();
    }
}
