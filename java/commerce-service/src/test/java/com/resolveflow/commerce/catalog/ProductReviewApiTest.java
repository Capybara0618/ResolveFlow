package com.resolveflow.commerce.catalog;

import com.resolveflow.commerce.CommerceDatabaseTest;
import com.resolveflow.shared.security.JwtCodec;
import com.resolveflow.shared.shopping.CheckoutWire.PayCommand;
import com.resolveflow.shared.shopping.ShoppingWire.*;
import java.time.Instant;
import java.util.UUID;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.resttestclient.autoconfigure.AutoConfigureRestTestClient;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.http.MediaType;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.test.web.servlet.client.RestTestClient;

@AutoConfigureRestTestClient
@SpringBootTest(webEnvironment = SpringBootTest.WebEnvironment.RANDOM_PORT)
class ProductReviewApiTest extends CommerceDatabaseTest {
    @Autowired
    RestTestClient rest;

    @Autowired
    JwtCodec codec;

    @Autowired
    ShoppingService shop;

    @Autowired
    CheckoutPayments payments;

    @Autowired
    JdbcTemplate jdbc;

    private String auth(String subject, String scope) {
        return "Bearer " + codec.issueServiceToken(subject, null, null, scope, Instant.now());
    }

    private String line() {
        var d = shop.create(new DraftCommand(
                "M-1001", "REVIEW-API", UUID.randomUUID().toString(), new DraftRequest("SKU-1001-BLACK", 1, 1L)));
        var p = payments.pay(
                d.draftId(),
                new PayCommand("M-1001", "REVIEW-API", UUID.randomUUID().toString()));
        jdbc.update(
                "UPDATE shipment SET status='DELIVERED',carrier_conclusion='DELIVERED',source_version=2 WHERE line_id=?",
                p.lineId());
        return p.lineId();
    }

    @Test
    void publicReviewsRequireServiceCredentialsAndHaveNoPrivateFields() {
        String url = "/internal/v1/shop/products/P-1001/reviews";
        rest.get().uri(url).exchange().expectStatus().isUnauthorized();
        rest.get()
                .uri(url)
                .header("Authorization", auth("case-service", "commerce:read"))
                .exchange()
                .expectStatus()
                .isOk()
                .expectBody()
                .jsonPath("$.summary.stars.length()")
                .isEqualTo(5);
    }

    @Test
    void agentCannotReadOrWritePrivateReviewsEvenWithForgedDeploymentScopes() {
        String token = auth("agent-service", "commerce:checkout commerce:fulfillment");
        rest.get()
                .uri("/internal/v1/shop/orders/lines/any/review?merchant_id=M-1001&buyer_id=OTHER")
                .header("Authorization", token)
                .exchange()
                .expectStatus()
                .isForbidden();
        rest.post()
                .uri("/internal/v1/shop/orders/lines/any/review")
                .header("Authorization", token)
                .contentType(MediaType.APPLICATION_JSON)
                .body("{}")
                .exchange()
                .expectStatus()
                .isForbidden();
        rest.get()
                .uri("/internal/v1/merchant/reviews?merchant_id=M-1001")
                .header("Authorization", token)
                .exchange()
                .expectStatus()
                .isForbidden();
        rest.post()
                .uri("/internal/v1/merchant/reviews/1/reply")
                .header("Authorization", token)
                .contentType(MediaType.APPLICATION_JSON)
                .body("{}")
                .exchange()
                .expectStatus()
                .isForbidden();
    }

    @Test
    void strictInputAndCompositeOwnershipAreEnforced() {
        String id = line(),
                url = "/internal/v1/shop/orders/lines/" + id + "/review",
                token = auth("case-service", "commerce:checkout");
        rest.get()
                .uri(url + "?merchant_id=M-1001&buyer_id=OTHER")
                .header("Authorization", token)
                .exchange()
                .expectStatus()
                .isNotFound();
        for (String rating : new String[] {"\"5\"", "4.5"}) {
            rest.post()
                    .uri(url)
                    .header("Authorization", token)
                    .contentType(MediaType.APPLICATION_JSON)
                    .body("{\"merchant_id\":\"M-1001\",\"buyer_id\":\"REVIEW-API\",\"request\":{\"rating\":" + rating
                            + ",\"body\":\"text\",\"expected_version\":0}}")
                    .exchange()
                    .expectStatus()
                    .isBadRequest();
        }
        rest.post()
                .uri(url)
                .header("Authorization", token)
                .contentType(MediaType.APPLICATION_JSON)
                .body(
                        "{\"merchant_id\":\"M-1001\",\"buyer_id\":\"REVIEW-API\",\"request\":{\"rating\":5,\"body\":\"text\",\"expected_version\":0,\"buyer_id\":\"injected\"}}")
                .exchange()
                .expectStatus()
                .isBadRequest();
        rest.post()
                .uri(url)
                .header("Authorization", token)
                .contentType(MediaType.APPLICATION_JSON)
                .body(
                        "{\"merchant_id\":\"M-1001\",\"buyer_id\":\"REVIEW-API\",\"request\":{\"rating\":5,\"body\":\"text\",\"expected_version\":0}}")
                .exchange()
                .expectStatus()
                .isOk()
                .expectBody()
                .jsonPath("$.version")
                .isEqualTo(1)
                .jsonPath("$.buyer_id")
                .doesNotExist();
    }
}
