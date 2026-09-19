package com.resolveflow.caseservice.order;

import static org.assertj.core.api.Assertions.assertThat;

import com.resolveflow.caseservice.order.CommerceOrderLineClient.OrderLineSummary;
import com.resolveflow.caseservice.order.CommerceOrderLineClient.PageMeta;
import com.resolveflow.shared.security.AuthenticatedPrincipal;
import com.resolveflow.shared.security.JwtCodec;
import com.resolveflow.shared.security.Role;
import java.time.Instant;
import java.util.List;
import java.util.Map;
import java.util.concurrent.atomic.AtomicReference;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.boot.resttestclient.autoconfigure.AutoConfigureRestTestClient;
import org.springframework.boot.test.context.TestConfiguration;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Primary;
import org.springframework.test.web.servlet.client.RestTestClient;
import org.springframework.web.client.RestClient;
import tools.jackson.databind.JsonNode;
import tools.jackson.databind.ObjectMapper;

/**
 * The public {@code /api/v1/orders} surface over real HTTP with Commerce stubbed.
 *
 * <p>Commerce is stubbed because the subject here is Case's half of the contract: which scope it
 * derives from the token, what it does with an order it cannot see, and how it reports a downstream
 * outage. The real cross-service call is exercised separately by running both services (see the C01.2c
 * record), because a stubbed downstream proves this side and nothing about the other.
 */
// The context now owns case_db, so these tests run against a real one too.
@AutoConfigureRestTestClient
class OrderApiTest extends com.resolveflow.caseservice.CaseDatabaseTest {

    private static final ObjectMapper MAPPER = new ObjectMapper();
    private static final String ORDER = "00000000-0000-4000-8000-0000000000aa";

    @Autowired
    RestTestClient rest;

    @Autowired
    StubCommerce commerce;

    @Autowired
    JwtCodec jwtCodec;

    @Value("${resolveflow.identity.jwt.secret}")
    String secret;

    /** A Commerce that answers canned pages and records what it was asked for. */
    static class StubCommerce extends CommerceOrderLineClient {

        final AtomicReference<AuthenticatedPrincipal> lastPrincipal = new AtomicReference<>();
        final AtomicReference<String> lastOrderId = new AtomicReference<>();
        volatile CommerceOrderLineClient.OrderLinePage next = page("7001");
        volatile RuntimeException failure;

        StubCommerce(RestClient.Builder builder, JwtCodec codec) {
            super(builder, codec, "http://commerce.stub", "case-service");
        }

        static CommerceOrderLineClient.OrderLinePage page(String... lineIds) {
            List<OrderLineSummary> items = java.util.Arrays.stream(lineIds)
                    .map(lineId -> new OrderLineSummary(
                            ORDER,
                            lineId,
                            "SKU-RED-M",
                            "apparel",
                            2,
                            2599,
                            "CNY",
                            Instant.parse("2026-09-10T08:15:00Z"),
                            "PAID",
                            3))
                    .toList();
            return new CommerceOrderLineClient.OrderLinePage(items, new PageMeta(null, 20));
        }

        @Override
        public CommerceOrderLineClient.OrderLinePage list(
                AuthenticatedPrincipal principal, String orderId, String cursor, Integer limit) {
            record(principal, orderId);
            return answer();
        }

        @Override
        public CommerceOrderLineClient.OrderLinePage readOrder(AuthenticatedPrincipal principal, String orderId) {
            record(principal, orderId);
            return answer();
        }

        private void record(AuthenticatedPrincipal principal, String orderId) {
            lastPrincipal.set(principal);
            lastOrderId.set(orderId);
        }

        private CommerceOrderLineClient.OrderLinePage answer() {
            if (failure != null) {
                throw failure;
            }
            return next;
        }
    }

    @TestConfiguration
    static class StubCommerceConfiguration {

        @Bean
        @Primary
        StubCommerce stubCommerce(RestClient.Builder builder, JwtCodec jwtCodec) {
            return new StubCommerce(builder, jwtCodec);
        }
    }

    private String customerToken() {
        return jwtCodec.issue(
                new AuthenticatedPrincipal("demo-customer", "M-1001", Role.CUSTOMER, "C-2002"), Instant.now());
    }

    private String reviewerToken() {
        return jwtCodec.issue(
                new AuthenticatedPrincipal("demo-reviewer", "M-1001", Role.REVIEWER, null), Instant.now());
    }

    @Test
    @DisplayName("a customer sees their own lines, and a query cannot widen the scope")
    void theScopeComesFromTheTokenOnly() {
        commerce.next = StubCommerce.page("7001", "7002");

        String body = rest.get()
                .uri("/api/v1/orders?merchant_id=M-1002&customer_id=C-2004&scope=all")
                .header("Authorization", "Bearer " + customerToken())
                .exchange()
                .expectStatus()
                .isOk()
                .expectBody(String.class)
                .returnResult()
                .getResponseBody();

        // The query string named another merchant and customer; the token decided, and the extra
        // parameters were not even read.
        assertThat(commerce.lastPrincipal.get().merchantId()).isEqualTo("M-1001");
        assertThat(commerce.lastPrincipal.get().customerId()).isEqualTo("C-2002");
        JsonNode json = MAPPER.readTree(body);
        assertThat(json.get("items")).hasSize(2);
        assertThat(json.get("page").get("limit").asInt()).isEqualTo(20);
    }

    @Test
    @DisplayName("a reviewer asks for the merchant, not for one customer")
    void aReviewerIsNotCustomerScoped() {
        commerce.next = StubCommerce.page("7001");

        rest.get()
                .uri("/api/v1/orders")
                .header("Authorization", "Bearer " + reviewerToken())
                .exchange()
                .expectStatus()
                .isOk();

        assertThat(commerce.lastPrincipal.get().role()).isEqualTo(Role.REVIEWER);
        assertThat(commerce.lastPrincipal.get().customerId()).isNull();
    }

    @Test
    @DisplayName("an order the principal cannot see is 404, not 403")
    void anInvisibleOrderIsNotFound() {
        commerce.next = StubCommerce.page();

        rest.get()
                .uri("/api/v1/orders/" + ORDER)
                .header("Authorization", "Bearer " + customerToken())
                .exchange()
                .expectStatus()
                .isNotFound()
                .expectBody(String.class)
                .value(body -> {
                    JsonNode json = MAPPER.readTree(body);
                    assertThat(json.get("code").stringValue()).isEqualTo("NOT_FOUND");
                    assertThat(json.get("message").stringValue())
                            .isEqualTo("the order does not exist under this principal");
                    assertThat(json.get("retryable").asBoolean()).isFalse();
                });
    }

    @Test
    @DisplayName("a visible order returns its lines in the documented shape")
    void aVisibleOrderIsReturned() {
        commerce.next = StubCommerce.page("7001", "7002");

        rest.get()
                .uri("/api/v1/orders/" + ORDER)
                .header("Authorization", "Bearer " + customerToken())
                .exchange()
                .expectStatus()
                .isOk()
                .expectBody(String.class)
                .value(body -> {
                    JsonNode line = MAPPER.readTree(body).get("items").get(0);
                    assertThat(line.get("line_id").stringValue()).isEqualTo("7001");
                    assertThat(line.get("line_paid_amount").asLong()).isEqualTo(2599);
                    assertThat(line.get("paid_at").stringValue()).isEqualTo("2026-09-10T08:15:00Z");
                });
        assertThat(commerce.lastOrderId.get()).isEqualTo(ORDER);
    }

    @Test
    @DisplayName("no token is 401 and Commerce is never called")
    void noTokenIsRefused() {
        commerce.lastPrincipal.set(null);

        rest.get()
                .uri("/api/v1/orders")
                .exchange()
                .expectStatus()
                .isUnauthorized()
                .expectBody(String.class)
                .value(body -> assertThat(MAPPER.readTree(body).get("code").stringValue())
                        .isEqualTo("UNAUTHENTICATED"));

        assertThat(commerce.lastPrincipal.get()).isNull();
    }

    @Test
    @DisplayName("a downstream outage is 503 retryable, not an empty order list")
    void anOutageIsServiceUnavailable() {
        commerce.failure = new CommerceOrderLineClient.CommerceUnavailableException("boom", new RuntimeException("x"));

        rest.get()
                .uri("/api/v1/orders")
                .header("Authorization", "Bearer " + customerToken())
                .exchange()
                .expectStatus()
                .isEqualTo(503)
                .expectBody(String.class)
                .value(body -> {
                    JsonNode json = MAPPER.readTree(body);
                    assertThat(json.get("code").stringValue()).isEqualTo("SERVICE_UNAVAILABLE");
                    assertThat(json.get("retryable").asBoolean()).isTrue();
                });
        commerce.failure = null;
    }

    @Test
    @DisplayName("the login route is unaffected: it still needs no token")
    void loginStaysOpen() {
        rest.post()
                .uri("/api/v1/auth/login")
                .contentType(org.springframework.http.MediaType.APPLICATION_JSON)
                .body(Map.of("username", "demo-customer", "password", "demo-pass-1001"))
                .exchange()
                .expectStatus()
                .isOk();
    }
}
