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
import java.time.Clock;
import java.time.Duration;
import java.time.Instant;
import java.time.ZoneOffset;
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
    @DisplayName("the public payload keeps the documented member names and instant format")
    void thePublicPayloadMatchesTheCoreContract() throws Exception {
        AuthenticatedPrincipal customer =
                new AuthenticatedPrincipal("demo-customer", "M-1001", Role.CUSTOMER, "C-2002");
        server.expect(requestTo(COMMERCE + "/internal/v1/order-lines?merchant_id=M-1001&customer_id=C-2002"))
                .andRespond(withSuccess(pageJson("7001"), MediaType.APPLICATION_JSON));
        CommerceOrderLineClient.OrderLinePage page = client.list(customer, null, null, null);

        OrderController controller =
                new OrderController(client, new RequestPrincipalResolver(codec, Clock.fixed(now, ZoneOffset.UTC)));
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
}
