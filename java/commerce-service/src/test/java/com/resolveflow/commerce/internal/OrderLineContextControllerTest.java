package com.resolveflow.commerce.internal;

import static org.assertj.core.api.Assertions.assertThat;

import com.resolveflow.commerce.CommerceDatabaseTest;
import com.resolveflow.shared.security.JwtCodec;
import java.time.Duration;
import java.time.Instant;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.boot.resttestclient.autoconfigure.AutoConfigureRestTestClient;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.test.web.servlet.client.RestTestClient;
import tools.jackson.databind.JsonNode;
import tools.jackson.databind.ObjectMapper;

/**
 * {@code GET /internal/v1/order-lines/{line_id}/context} over HTTP (C03.2a).
 *
 * <p>This is the read Java recomputes a refund from, so the test is about the money being real: the amounts
 * come from {@code payment_ledger} rather than from a constant, the ownership is disclosed so the caller can
 * confirm it, and the route carries no scope of its own — which is only safe because it is service-only.
 */
@SpringBootTest(webEnvironment = SpringBootTest.WebEnvironment.RANDOM_PORT)
@AutoConfigureRestTestClient
class OrderLineContextControllerTest extends CommerceDatabaseTest {

    private static final ObjectMapper MAPPER = new ObjectMapper();

    @Autowired
    RestTestClient rest;

    @Autowired
    JdbcTemplate jdbc;

    @Value("${resolveflow.identity.jwt.secret}")
    String secret;

    @AfterEach
    void restoreLedger() {
        jdbc.update("UPDATE payment_ledger SET refunded_amount = 0, reserved_refund_amount = 0, version = 1"
                + " WHERE order_id = '00000000-0000-4000-8000-0000000000aa'");
    }

    private String serviceToken() {
        return new JwtCodec(secret, Duration.ofHours(1)).issueServiceToken("case-service", Instant.now());
    }

    private String userToken() {
        return new JwtCodec(secret, Duration.ofHours(1))
                .issue(
                        new com.resolveflow.shared.security.AuthenticatedPrincipal(
                                "demo-customer", "M-1001", com.resolveflow.shared.security.Role.CUSTOMER, "C-2002"),
                        Instant.now());
    }

    private JsonNode context(String lineId) {
        return MAPPER.readTree(rest.get()
                .uri("/internal/v1/order-lines/" + lineId + "/context")
                .header("Authorization", "Bearer " + serviceToken())
                .exchange()
                .expectStatus()
                .isOk()
                .expectBody(String.class)
                .returnResult()
                .getResponseBody());
    }

    @Test
    @DisplayName("the context is the contract's members, and it carries the ownership the caller verifies")
    void theContextIsTheContractShape() {
        JsonNode json = context("7001");

        assertThat(json.properties().stream().map(java.util.Map.Entry::getKey))
                .containsExactlyInAnyOrder(
                        "order_id",
                        "line_id",
                        "merchant_id",
                        "customer_id",
                        "sku",
                        "category",
                        "quantity",
                        "line_paid_amount",
                        "refunded_amount",
                        "reserved_refund_amount",
                        "currency",
                        "paid_at",
                        "order_status",
                        "version");
        assertThat(json.get("merchant_id").stringValue())
                .as("a service re-checking a case needs to confirm the line belongs to that case")
                .isEqualTo("M-1001");
        assertThat(json.get("customer_id").stringValue()).isEqualTo("C-2002");
        assertThat(json.get("line_paid_amount").asLong()).isEqualTo(2599);
        assertThat(json.get("refunded_amount").asLong()).isZero();
        assertThat(json.get("reserved_refund_amount").asLong()).isZero();
        assertThat(json.get("currency").stringValue()).isEqualTo("CNY");
        assertThat(json.get("paid_at").stringValue())
                .as("a UTC instant with a trailing Z, which is what the policy window is compared against")
                .isEqualTo("2026-09-10T08:15:00Z");
        assertThat(json.get("order_status").stringValue()).isEqualTo("PAID");
        assertThat(json.get("version").asLong()).isEqualTo(3);
    }

    @Test
    @DisplayName("the ledger amounts are read, not hardcoded: moving money moves the context")
    void theLedgerAmountsAreTheLedgersOwn() {
        jdbc.update("UPDATE payment_ledger SET refunded_amount = 500, reserved_refund_amount = 100, version = 2"
                + " WHERE order_id = '00000000-0000-4000-8000-0000000000aa'");

        JsonNode json = context("7001");
        assertThat(json.get("refunded_amount").asLong())
                .as("this is the number a recomputation refuses a second refund with")
                .isEqualTo(500);
        assertThat(json.get("reserved_refund_amount").asLong()).isEqualTo(100);

        // And the listing is a different view of the same line: it carries no money that has moved.
        JsonNode listing = MAPPER.readTree(rest.get()
                .uri("/internal/v1/order-lines?merchant_id=M-1001&customer_id=C-2002")
                .header("Authorization", "Bearer " + serviceToken())
                .exchange()
                .expectStatus()
                .isOk()
                .expectBody(String.class)
                .returnResult()
                .getResponseBody());
        assertThat(listing.get("items").get(0).has("refunded_amount")).isFalse();
        assertThat(listing.get("items").get(0).has("merchant_id"))
                .as("the listing does not echo the scope back; the context must, to be verifiable")
                .isFalse();
    }

    @Test
    @DisplayName("an unknown line is 404, and the route is service-only")
    void theRouteIsServiceOnlyAndUnknownLinesAreNotFound() {
        rest.get()
                .uri("/internal/v1/order-lines/does-not-exist/context")
                .header("Authorization", "Bearer " + serviceToken())
                .exchange()
                .expectStatus()
                .isNotFound()
                .expectBody(String.class)
                .value(response -> {
                    JsonNode json = MAPPER.readTree(response);
                    assertThat(json.get("code").stringValue()).isEqualTo("NOT_FOUND");
                    assertThat(json.get("message").stringValue()).isEqualTo("no such order line: does-not-exist");
                });

        rest.get()
                .uri("/internal/v1/order-lines/7001/context")
                .exchange()
                .expectStatus()
                .isUnauthorized();

        rest.get()
                .uri("/internal/v1/order-lines/7001/context")
                .header("Authorization", "Bearer " + userToken())
                .exchange()
                .expectStatus()
                .isForbidden();
    }
}
