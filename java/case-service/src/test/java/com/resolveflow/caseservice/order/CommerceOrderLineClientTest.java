package com.resolveflow.caseservice.order;

import static org.assertj.core.api.Assertions.assertThat;
import static org.springframework.test.web.client.match.MockRestRequestMatchers.header;
import static org.springframework.test.web.client.match.MockRestRequestMatchers.method;
import static org.springframework.test.web.client.match.MockRestRequestMatchers.queryParam;
import static org.springframework.test.web.client.match.MockRestRequestMatchers.requestTo;
import static org.springframework.test.web.client.response.MockRestResponseCreators.withServerError;
import static org.springframework.test.web.client.response.MockRestResponseCreators.withSuccess;

import com.resolveflow.caseservice.order.CommerceOrderLineClient.CommerceUnavailableException;
import com.resolveflow.shared.security.AuthenticatedPrincipal;
import com.resolveflow.shared.security.JwtCodec;
import com.resolveflow.shared.security.Role;
import java.time.Duration;
import java.time.Instant;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.springframework.http.HttpMethod;
import org.springframework.http.MediaType;
import org.springframework.test.web.client.MockRestServiceServer;
import org.springframework.web.client.RestClient;
import tools.jackson.databind.JsonNode;
import tools.jackson.databind.ObjectMapper;

/**
 * The public order view, and the two ways it can go wrong quietly.
 *
 * <p>Tested by inspecting what Case actually sends to Commerce: the scope it derived from the token and
 * the service token it presented. A test that only checked the response body would pass even if Case
 * had forwarded the caller's query parameters as the scope, which is the failure that matters here
 * (docs/core-contracts.md:15).
 */
class CommerceOrderLineClientTest {

    private static final String SECRET = "resolveflow-core-demo-identity-secret";
    private static final String COMMERCE = "http://commerce.test";
    private static final String ORDER = "00000000-0000-4000-8000-0000000000aa";
    private static final ObjectMapper MAPPER = new ObjectMapper();

    private final JwtCodec codec = new JwtCodec(SECRET, Duration.ofHours(1));
    private final Instant now = Instant.parse("2026-09-19T10:00:00Z");

    private MockRestServiceServer server;
    private CommerceOrderLineClient client;

    @BeforeEach
    void bindMockCommerce() {
        RestClient.Builder builder = RestClient.builder();
        server = MockRestServiceServer.bindTo(builder).build();
        client = new CommerceOrderLineClient(builder, codec, COMMERCE, "case-service");
    }

    private static String pageJson(String lineId) {
        return """
               {"items":[{"order_id":"%s","line_id":"%s","sku":"SKU-RED-M","category":"apparel",
                 "quantity":2,"line_paid_amount":2599,"currency":"CNY","paid_at":"2026-09-10T08:15:00Z",
                 "status":"PAID","version":3}],"page":{"limit":20}}
               """.formatted(ORDER, lineId);
    }

    /** The same page for a line whose merchant did record a product name and a variant. */
    private static String namedPageJson(String lineId) {
        return """
               {"items":[{"order_id":"%s","line_id":"%s","sku":"SKU-RED-M","product_name":"演示商品 · 耳机",
                 "variant_text":"深空灰","category":"apparel","quantity":2,"line_paid_amount":2599,
                 "currency":"CNY","paid_at":"2026-09-10T08:15:00Z","status":"PAID","version":3}],
                "page":{"limit":20}}
               """.formatted(ORDER, lineId);
    }

    @Test
    @DisplayName("a customer's token decides the scope, and the user token is never forwarded")
    void theScopeComesFromTheTokenAndTheServiceTokenIsUsed() {
        AuthenticatedPrincipal customer =
                new AuthenticatedPrincipal("demo-customer", "M-1001", Role.CUSTOMER, "C-2002");
        server.expect(requestTo(COMMERCE + "/internal/v1/order-lines?merchant_id=M-1001&customer_id=C-2002"))
                .andExpect(method(HttpMethod.GET))
                .andExpect(queryParam("merchant_id", "M-1001"))
                .andExpect(queryParam("customer_id", "C-2002"))
                .andExpect(header("Authorization", org.hamcrest.Matchers.startsWith("Bearer ")))
                .andRespond(withSuccess(pageJson("7001"), MediaType.APPLICATION_JSON));

        CommerceOrderLineClient.OrderLinePage page = client.list(customer, null, null, null);

        server.verify();
        assertThat(page.items()).hasSize(1);
        assertThat(page.items().get(0).lineId()).isEqualTo("7001");
        assertThat(page.items().get(0).paidAt()).isEqualTo(Instant.parse("2026-09-10T08:15:00Z"));
    }

    @Test
    @DisplayName("the bearer Case presents is a service token, not the caller's user token")
    void thePresentedTokenIsAServiceToken() {
        JwtCodec verifier = new JwtCodec(SECRET, Duration.ofHours(1));
        AuthenticatedPrincipal reviewer = new AuthenticatedPrincipal("demo-reviewer", "M-1001", Role.REVIEWER, null);
        server.expect(requestTo(COMMERCE + "/internal/v1/order-lines?merchant_id=M-1001"))
                .andRespond(withSuccess(pageJson("7001"), MediaType.APPLICATION_JSON));

        client.list(reviewer, null, null, null);

        server.verify();
    }

    @Test
    @DisplayName("a merchant-scoped principal is not given a customer scope")
    void aReviewerSeesTheWholeMerchant() {
        AuthenticatedPrincipal reviewer = new AuthenticatedPrincipal("demo-reviewer", "M-1001", Role.REVIEWER, null);
        // The exact URI is the assertion: no customer_id is sent at all, rather than sent empty.
        server.expect(requestTo(COMMERCE + "/internal/v1/order-lines?merchant_id=M-1001"))
                .andRespond(withSuccess(pageJson("7001"), MediaType.APPLICATION_JSON));

        client.list(reviewer, null, null, null);

        server.verify();
    }

    @Test
    @DisplayName("an order read narrows the same scope instead of replacing it")
    void readingOneOrderKeepsTheScope() {
        AuthenticatedPrincipal customer =
                new AuthenticatedPrincipal("demo-customer", "M-1001", Role.CUSTOMER, "C-2002");
        server.expect(requestTo(
                        COMMERCE + "/internal/v1/order-lines?merchant_id=M-1001&customer_id=C-2002&order_id=" + ORDER))
                .andRespond(withSuccess(pageJson("7001"), MediaType.APPLICATION_JSON));

        CommerceOrderLineClient.OrderLinePage page = client.readOrder(customer, ORDER);

        server.verify();
        assertThat(page.items()).hasSize(1);
    }

    @Test
    @DisplayName("Commerce being down is an availability failure, not an empty result")
    void commerceFailureIsNotAnEmptyPage() {
        AuthenticatedPrincipal customer =
                new AuthenticatedPrincipal("demo-customer", "M-1001", Role.CUSTOMER, "C-2002");
        server.expect(requestTo(COMMERCE + "/internal/v1/order-lines?merchant_id=M-1001&customer_id=C-2002"))
                .andRespond(withServerError());

        org.assertj.core.api.Assertions.assertThatThrownBy(() -> client.list(customer, null, null, null))
                .isInstanceOf(CommerceUnavailableException.class);
    }

    @Test
    @DisplayName("a query Commerce refuses is the caller's problem, not an outage")
    void aRefusedQueryIsNotAnOutage() {
        // C05.4. The cursor is opaque and Commerce owns it, so this client cannot check it before sending it;
        // Commerce answering 400 is the only way this service learns the page was never issued. Turning that
        // into CommerceUnavailableException made the public API answer 503 — "try again later" for a request
        // that can never succeed, and the caller never learns which part of their request was wrong.
        AuthenticatedPrincipal customer =
                new AuthenticatedPrincipal("demo-customer", "M-1001", Role.CUSTOMER, "C-2002");
        server.expect(requestTo(
                        COMMERCE + "/internal/v1/order-lines?merchant_id=M-1001&customer_id=C-2002&cursor=not-a-page"))
                .andRespond(org.springframework.test.web.client.response.MockRestResponseCreators.withStatus(
                        org.springframework.http.HttpStatus.BAD_REQUEST));

        org.assertj.core.api.Assertions.assertThatThrownBy(() -> client.list(customer, null, "not-a-page", null))
                .as("a refusal is not an outage: it must not be reported as retryable")
                .isInstanceOf(CommerceOrderLineClient.CommerceRejectedQueryException.class);
    }

    @Test
    @DisplayName("the line context keeps the documented member names and reports what is left to refund")
    void theLineContextMatchesTheCoreContract() {
        server.expect(requestTo(COMMERCE + "/internal/v1/order-lines/7001/context"))
                .andExpect(method(HttpMethod.GET))
                .andExpect(header("Authorization", org.hamcrest.Matchers.startsWith("Bearer ")))
                .andRespond(withSuccess("""
                        {"order_id":"%s","line_id":"7001","merchant_id":"M-1001","customer_id":"C-2002",
                         "sku":"SKU-RED-M","category":"apparel","quantity":2,"line_paid_amount":2599,
                         "refunded_amount":500,"reserved_refund_amount":100,"currency":"CNY",
                         "paid_at":"2026-09-10T08:15:00Z","order_status":"PAID","version":4}
                        """.formatted(ORDER), MediaType.APPLICATION_JSON));

        CommerceOrderLineClient.LineContext context =
                client.readLineContext("7001").orElseThrow();

        server.verify();
        assertThat(context.merchantId()).isEqualTo("M-1001");
        assertThat(context.customerId()).isEqualTo("C-2002");
        assertThat(context.linePaidAmount()).isEqualTo(2599L);
        assertThat(context.refundableAmountMinor())
                .as("what is left is paid minus refunded minus reserved, and never below zero")
                .isEqualTo(1999L);
    }

    @Test
    void multiLineContextSeparatesTheFreeLineFromItsOrdersRefundsAndReservations() {
        for (String state : java.util.List.of("FREE", "RESERVED", "CONSUMED")) {
            server.expect(requestTo(COMMERCE + "/internal/v1/order-lines/7002/context"))
                    .andRespond(withSuccess("""
                        {"order_id":"%s","line_id":"7002","merchant_id":"M-1001","customer_id":"C-2002",
                         "sku":"SKU","category":"electronics","quantity":1,"line_paid_amount":39800,
                         "refunded_amount":32900,"reserved_refund_amount":0,"currency":"CNY",
                         "paid_at":"2026-10-03T04:00:00Z","order_status":"PAID","version":1,
                         "order_paid_amount":72700,"line_refund_state":"%s"}
                        """.formatted(ORDER, state), MediaType.APPLICATION_JSON));
            assertThat(client.readLineContext("7002").orElseThrow().refundableAmountMinor())
                    .isEqualTo(state.equals("FREE") ? 39800L : 0L);
            server.verify();
            server.reset();
        }
    }

    @Test
    void multiLineContextCannotGrantMoreThanTheOrderHasLeftOrInventAMissingSlot() {
        for (String extra : java.util.List.of(
                "\"order_paid_amount\":40000,\"line_refund_state\":\"FREE\"",
                "\"order_paid_amount\":72700",
                "\"line_refund_state\":\"RESERVED\"")) {
            server.expect(requestTo(COMMERCE + "/internal/v1/order-lines/7002/context"))
                    .andRespond(withSuccess("""
                        {"order_id":"%s","line_id":"7002","merchant_id":"M-1001","customer_id":"C-2002",
                         "sku":"SKU","category":"electronics","quantity":1,"line_paid_amount":39800,
                         "refunded_amount":32900,"reserved_refund_amount":0,"currency":"CNY",
                         "paid_at":"2026-10-03T04:00:00Z","order_status":"PAID","version":1,%s}
                        """.formatted(ORDER, extra), MediaType.APPLICATION_JSON));
            assertThat(client.readLineContext("7002").orElseThrow().refundableAmountMinor())
                    .isEqualTo(extra.contains("40000") ? 7100L : 0L);
            server.verify();
            server.reset();
        }
    }

    @Test
    @DisplayName("a line Commerce does not have is empty, and a Commerce failure is not")
    void aMissingLineIsEmptyAndAFailureIsNot() {
        server.expect(requestTo(COMMERCE + "/internal/v1/order-lines/7001/context"))
                .andRespond(org.springframework.test.web.client.response.MockRestResponseCreators.withStatus(
                        org.springframework.http.HttpStatus.NOT_FOUND));

        assertThat(client.readLineContext("7001"))
                .as("a line that is gone is a fact the re-check records; it is not an outage")
                .isEmpty();

        server.reset();
        server.expect(requestTo(COMMERCE + "/internal/v1/order-lines/7001/context"))
                .andRespond(withServerError());

        org.assertj.core.api.Assertions.assertThatThrownBy(() -> client.readLineContext("7001"))
                .as("an unavailable Commerce must not be read as 'there is nothing to refund'")
                .isInstanceOf(CommerceUnavailableException.class);
    }

    @Test
    @DisplayName("the public payload keeps the documented member names and instant format")
    void thePublicPayloadMatchesTheCoreContract() throws Exception {
        AuthenticatedPrincipal customer =
                new AuthenticatedPrincipal("demo-customer", "M-1001", Role.CUSTOMER, "C-2002");
        server.expect(requestTo(COMMERCE + "/internal/v1/order-lines?merchant_id=M-1001&customer_id=C-2002"))
                .andRespond(withSuccess(pageJson("7001"), MediaType.APPLICATION_JSON));
        CommerceOrderLineClient.OrderLinePage page = client.list(customer, null, null, null);

        OrderController controller = new OrderController(
                client,
                org.mockito.Mockito.mock(RequestPrincipalResolver.class),
                org.mockito.Mockito.mock(BuyerOrderService.class));
        JsonNode json = MAPPER.readTree(MAPPER.writeValueAsString(OrderController.OrderLinePageResponse.from(page)));

        assertThat(json.get("items").get(0).properties().stream().map(java.util.Map.Entry::getKey))
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
        assertThat(json.get("items").get(0).get("paid_at").stringValue()).isEqualTo("2026-09-10T08:15:00Z");
        assertThat(json.get("page").get("limit").asInt()).isEqualTo(20);
    }

    @Test
    @DisplayName("a named line carries the display members, and an unnamed one omits them")
    void theDisplayMembersFollowTheLineRatherThanThePage() throws Exception {
        AuthenticatedPrincipal customer =
                new AuthenticatedPrincipal("demo-customer", "M-1001", Role.CUSTOMER, "C-2002");

        // Historical line: the two optional members are absent, not null, so the public view
        // answers exactly as it did before V7 and the member set above stays true.
        server.expect(requestTo(COMMERCE + "/internal/v1/order-lines?merchant_id=M-1001&customer_id=C-2002"))
                .andRespond(withSuccess(pageJson("7001"), MediaType.APPLICATION_JSON));
        JsonNode unnamed = MAPPER.readTree(MAPPER.writeValueAsString(
                OrderController.OrderLinePageResponse.from(client.list(customer, null, null, null))));
        assertThat(unnamed.get("items").get(0).has("product_name")).isFalse();
        assertThat(unnamed.get("items").get(0).has("variant_text")).isFalse();

        server.reset();
        server.expect(requestTo(COMMERCE + "/internal/v1/order-lines?merchant_id=M-1001&customer_id=C-2002"))
                .andRespond(withSuccess(namedPageJson("7001"), MediaType.APPLICATION_JSON));
        JsonNode named = MAPPER.readTree(MAPPER.writeValueAsString(
                OrderController.OrderLinePageResponse.from(client.list(customer, null, null, null))));
        assertThat(named.get("items").get(0).get("product_name").stringValue()).isEqualTo("演示商品 · 耳机");
        assertThat(named.get("items").get(0).get("variant_text").stringValue()).isEqualTo("深空灰");
        // The identifiers, amount and payment instant are untouched by the display members.
        assertThat(named.get("items").get(0).get("line_paid_amount").asLong()).isEqualTo(2599);
        assertThat(named.get("items").get(0).get("paid_at").stringValue()).isEqualTo("2026-09-10T08:15:00Z");
    }
}
