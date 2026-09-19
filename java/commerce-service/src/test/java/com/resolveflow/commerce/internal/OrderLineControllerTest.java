package com.resolveflow.commerce.internal;

import static org.assertj.core.api.Assertions.assertThat;

import com.resolveflow.commerce.CommerceDatabaseTest;
import com.resolveflow.shared.security.JwtCodec;
import java.time.Duration;
import java.time.Instant;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.boot.resttestclient.autoconfigure.AutoConfigureRestTestClient;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.test.web.servlet.client.RestTestClient;
import tools.jackson.databind.JsonNode;
import tools.jackson.databind.ObjectMapper;

/**
 * {@code GET /internal/v1/order-lines} over HTTP, against the real seed.
 *
 * <p>Two things are being proved at once: the response is the core OpenAPI shape (snake_case members,
 * a UTC {@code paid_at}, {@code next_cursor} present exactly when there is more), and the internal
 * surface really is service-only — a user token, however valid, cannot name a merchant scope here
 * (docs/core-contracts.md:15,26).
 */
@SpringBootTest(webEnvironment = SpringBootTest.WebEnvironment.RANDOM_PORT)
@AutoConfigureRestTestClient
class OrderLineControllerTest extends CommerceDatabaseTest {

    private static final ObjectMapper MAPPER = new ObjectMapper();

    @Autowired
    RestTestClient rest;

    @Value("${resolveflow.identity.jwt.secret}")
    String secret;

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

    private String body(String token, String query) {
        return rest.get()
                .uri("/internal/v1/order-lines?" + query)
                .header("Authorization", "Bearer " + token)
                .exchange()
                .expectStatus()
                .isOk()
                .expectBody(String.class)
                .returnResult()
                .getResponseBody();
    }

    @Test
    @DisplayName("a customer scope returns that customer's lines in the documented shape")
    void customerScopeReturnsTheDocumentedShape() {
        JsonNode json = MAPPER.readTree(body(serviceToken(), "merchant_id=M-1001&customer_id=C-2002"));

        assertThat(json.get("items")).hasSize(2);
        JsonNode line = json.get("items").get(0);
        assertThat(line.properties().stream().map(java.util.Map.Entry::getKey))
                .containsExactlyInAnyOrder(
                        "order_id",
                        "line_id",
                        "sku",
                        "category",
                        "quantity",
                        "line_paid_amount",
                        "currency",
                        "paid_at",
                        "status",
                        "version");
        assertThat(line.get("line_id").stringValue()).isEqualTo("7002");
        assertThat(line.get("line_paid_amount").asLong()).isEqualTo(1999);
        assertThat(line.get("currency").stringValue()).isEqualTo("CNY");
        assertThat(line.get("paid_at").stringValue())
                .as("a UTC instant with a trailing Z, not a local timestamp (docs/core-contracts.md:17)")
                .isEqualTo("2026-09-10T08:15:00Z");
        assertThat(json.get("page").get("limit").asInt()).isEqualTo(20);
        // "No next page" is the absence of next_cursor, not a null member: one fact, one
        // representation (the same rule the core protocol applies to optional members).
        assertThat(json.get("page").has("next_cursor")).isFalse();
    }

    @Test
    @DisplayName("a merchant scope sees the merchant and not the other one")
    void merchantScopeIsHonoured() {
        JsonNode json = MAPPER.readTree(body(serviceToken(), "merchant_id=M-1001"));

        assertThat(json.get("items")).hasSize(3);
        assertThat(json.get("items").toString()).doesNotContain("7201").doesNotContain("M-1002");
    }

    @Test
    @DisplayName("an order filter returns that order's lines inside the scope, and nothing otherwise")
    void anOrderFilterNarrowsInsideTheScope() {
        JsonNode mine = MAPPER.readTree(body(
                serviceToken(), "merchant_id=M-1001&customer_id=C-2002&order_id=00000000-0000-4000-8000-0000000000aa"));
        assertThat(mine.get("items")).hasSize(2);
        assertThat(mine.get("items").toString()).doesNotContain("7101");

        // The same order, asked for by the other merchant: an empty page, not an error and not the
        // lines themselves. Case turns this into a 404 (docs/core-contracts.md:27).
        JsonNode foreign = MAPPER.readTree(
                body(serviceToken(), "merchant_id=M-1002&order_id=00000000-0000-4000-8000-0000000000aa"));
        assertThat(foreign.get("items")).isEmpty();
    }

    @Test
    void theCursorPages() {
        JsonNode first = MAPPER.readTree(body(serviceToken(), "merchant_id=M-1001&limit=1"));
        assertThat(first.get("items")).hasSize(1);
        assertThat(first.get("page").get("limit").asInt()).isEqualTo(1);
        String cursor = first.get("page").get("next_cursor").stringValue();

        JsonNode second = MAPPER.readTree(body(
                serviceToken(),
                "merchant_id=M-1001&limit=1&cursor="
                        + java.net.URLEncoder.encode(cursor, java.nio.charset.StandardCharsets.UTF_8)));

        assertThat(second.get("items").get(0).get("line_id").stringValue())
                .isNotEqualTo(first.get("items").get(0).get("line_id").stringValue());
    }

    @Test
    @DisplayName("no token at all is 401, and a user token is refused as a scope problem")
    void theInternalSurfaceIsServiceOnly() {
        rest.get()
                .uri("/internal/v1/order-lines?merchant_id=M-1001")
                .exchange()
                .expectStatus()
                .isUnauthorized()
                .expectBody(String.class)
                .value(response -> assertThat(
                                MAPPER.readTree(response).get("code").stringValue())
                        .isEqualTo("UNAUTHENTICATED"));

        rest.get()
                .uri("/internal/v1/order-lines?merchant_id=M-1001")
                .header("Authorization", "Bearer " + userToken())
                .exchange()
                .expectStatus()
                .isForbidden()
                .expectBody(String.class)
                .value(response -> {
                    JsonNode json = MAPPER.readTree(response);
                    assertThat(json.get("code").stringValue()).isEqualTo("FORBIDDEN_SCOPE");
                    assertThat(json.get("retryable").asBoolean()).isFalse();
                    assertThat(json.get("trace_id").isNull()).isFalse();
                });
    }

    @Test
    @DisplayName("a missing scope or a broken cursor is 400 in the shared error shape")
    void badInputIsRejectedNotIgnored() {
        rest.get()
                .uri("/internal/v1/order-lines")
                .header("Authorization", "Bearer " + serviceToken())
                .exchange()
                .expectStatus()
                .isBadRequest()
                .expectBody(String.class)
                .value(response -> assertThat(
                                MAPPER.readTree(response).get("code").stringValue())
                        .isEqualTo("INVALID_ARGUMENT"));

        rest.get()
                .uri("/internal/v1/order-lines?merchant_id=M-1001&cursor=Zm9v")
                .header("Authorization", "Bearer " + serviceToken())
                .exchange()
                .expectStatus()
                .isBadRequest()
                .expectBody(String.class)
                .value(response -> assertThat(
                                MAPPER.readTree(response).get("message").stringValue())
                        .isEqualTo("cursor was not issued by this service"));

        rest.get()
                .uri("/internal/v1/order-lines?merchant_id=M-1001&limit=0")
                .header("Authorization", "Bearer " + serviceToken())
                .exchange()
                .expectStatus()
                .isBadRequest();
    }

    @Test
    @DisplayName("health stays open: the gateway probes it without a service token")
    void healthNeedsNoToken() {
        rest.get().uri("/actuator/health").exchange().expectStatus().isOk();
    }
}
