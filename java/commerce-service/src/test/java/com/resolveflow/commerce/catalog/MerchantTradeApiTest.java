package com.resolveflow.commerce.catalog;

import com.resolveflow.commerce.CommerceDatabaseTest;
import com.resolveflow.shared.security.JwtCodec;
import com.resolveflow.shared.shopping.CheckoutWire.PayCommand;
import com.resolveflow.shared.shopping.ShoppingWire.*;
import java.time.Instant;
import java.util.Map;
import java.util.UUID;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.resttestclient.autoconfigure.AutoConfigureRestTestClient;
import org.springframework.http.MediaType;
import org.springframework.test.web.servlet.client.RestTestClient;

@AutoConfigureRestTestClient
@org.springframework.boot.test.context.SpringBootTest(
        webEnvironment = org.springframework.boot.test.context.SpringBootTest.WebEnvironment.RANDOM_PORT)
class MerchantTradeApiTest extends CommerceDatabaseTest {
    @Autowired
    RestTestClient rest;

    @Autowired
    JwtCodec codec;

    @Autowired
    ShoppingService shop;

    @Autowired
    CheckoutPayments payments;

    private String token(String subject, String scope) {
        return "Bearer " + codec.issueServiceToken(subject, null, null, scope, Instant.now());
    }

    @Test
    void merchantReadWriteIsCaseFulfillmentOnlyAndBuyerReadHasSeparateCheckoutScope() {
        rest.get()
                .uri("/internal/v1/merchant/orders?merchant_id=M-1001")
                .exchange()
                .expectStatus()
                .isUnauthorized();
        for (var pair : new String[][] {
            {"agent-service", "commerce:read"},
            {"agent-service", "commerce:fulfillment"},
            {"case-service", "commerce:checkout"},
            {"case-service", "commerce:read"}
        }) {
            String auth = token(pair[0], pair[1]);
            for (var path : java.util.List.of(
                    "/internal/v1/merchant/orders?merchant_id=M-1001",
                    "/internal/v1/merchant/orders/unknown?merchant_id=M-1001"))
                rest.get()
                        .uri(path)
                        .header("Authorization", auth)
                        .exchange()
                        .expectStatus()
                        .isForbidden();
            rest.post()
                    .uri("/internal/v1/merchant/orders/unknown/simulated-shipment")
                    .header("Authorization", auth)
                    .contentType(MediaType.APPLICATION_JSON)
                    .body("{}")
                    .exchange()
                    .expectStatus()
                    .isForbidden();
        }
        rest.get()
                .uri("/internal/v1/shop/orders/unknown/fulfillment?merchant_id=M-1001&customer_id=OTHER")
                .header("Authorization", token("agent-service", "commerce:checkout"))
                .exchange()
                .expectStatus()
                .isForbidden();
        rest.get()
                .uri("/internal/v1/shop/orders/unknown/fulfillment?merchant_id=M-1001&customer_id=OTHER")
                .header("Authorization", token("case-service", "commerce:fulfillment"))
                .exchange()
                .expectStatus()
                .isForbidden();
    }

    @Test
    void actualPaidOrderCanShipOnceWithVersionAndHasNoPublicRequestKey() {
        var d = shop.create(new DraftCommand(
                "M-1001",
                "MERCHANT-API-TEST",
                UUID.randomUUID().toString(),
                new DraftRequest("SKU-1001-BLACK", 1, 1L)));
        String id = payments.pay(
                        d.draftId(),
                        new PayCommand(
                                "M-1001", "MERCHANT-API-TEST", UUID.randomUUID().toString()))
                .orderId();
        String auth = token("case-service", "commerce:fulfillment");
        rest.get()
                .uri("/internal/v1/merchant/orders/" + id + "?merchant_id=M-1001")
                .header("Authorization", auth)
                .exchange()
                .expectStatus()
                .isOk()
                .expectBody()
                .jsonPath("$.can_ship")
                .isEqualTo(true)
                .jsonPath("$.fulfillment.status")
                .isEqualTo("NOT_SHIPPED")
                .jsonPath("$.shipment_key")
                .doesNotExist();
        var command = Map.of(
                "merchant_id",
                "M-1001",
                "actor",
                "demo-admin",
                "idempotency_key",
                "original-ship",
                "expected_version",
                1);
        for (int i = 0; i < 2; i++)
            rest.post()
                    .uri("/internal/v1/merchant/orders/" + id + "/simulated-shipment")
                    .header("Authorization", auth)
                    .contentType(MediaType.APPLICATION_JSON)
                    .body(command)
                    .exchange()
                    .expectStatus()
                    .isOk()
                    .expectBody()
                    .jsonPath("$.status")
                    .isEqualTo("IN_TRANSIT")
                    .jsonPath("$.version")
                    .isEqualTo(2)
                    .jsonPath("$.lines[0].events.length()")
                    .isEqualTo(2);
        rest.get()
                .uri("/internal/v1/merchant/orders/" + id + "?merchant_id=M-1002")
                .header("Authorization", auth)
                .exchange()
                .expectStatus()
                .isNotFound();
        for (var customer : java.util.List.of("MERCHANT-API-TEST", "FOREIGN"))
            rest.get()
                    .uri("/internal/v1/shop/orders/" + id + "/fulfillment?merchant_id=M-1001&customer_id=" + customer)
                    .header("Authorization", token("case-service", "commerce:checkout"))
                    .exchange()
                    .expectStatus()
                    .isEqualTo(customer.equals("FOREIGN") ? 404 : 200);
        rest.get()
                .uri("/internal/v1/merchant/orders?merchant_id=M-1001&status=PAID")
                .header("Authorization", auth)
                .exchange()
                .expectStatus()
                .isBadRequest();
    }
}
