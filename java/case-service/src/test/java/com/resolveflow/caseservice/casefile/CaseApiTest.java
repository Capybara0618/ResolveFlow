package com.resolveflow.caseservice.casefile;

import static org.assertj.core.api.Assertions.assertThat;

import com.resolveflow.caseservice.CaseDatabaseTest;
import com.resolveflow.shared.security.AuthenticatedPrincipal;
import com.resolveflow.shared.security.JwtCodec;
import com.resolveflow.shared.security.Role;
import java.time.Instant;
import java.util.Map;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.boot.resttestclient.autoconfigure.AutoConfigureRestTestClient;
import org.springframework.boot.test.context.TestConfiguration;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Primary;
import org.springframework.http.HttpHeaders;
import org.springframework.http.MediaType;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.test.web.servlet.client.RestTestClient;
import org.springframework.web.client.RestClient;
import tools.jackson.databind.JsonNode;
import tools.jackson.databind.ObjectMapper;

/**
 * {@code POST /api/v1/cases} over real HTTP against a real case_db.
 *
 * <p>Each acceptance condition of C02.1 is one test here: the same key with a different body is 409,
 * the same line cannot have two open cases, the line must be inside the caller's scope, the first
 * trajectory entry is written with the case rather than after it, and the stored answer is what a
 * repeat replays.
 */
@AutoConfigureRestTestClient
class CaseApiTest extends CaseDatabaseTest {

    private static final ObjectMapper MAPPER = new ObjectMapper();
    private static final String LINE = "7001";

    @Autowired
    RestTestClient rest;

    @Autowired
    StubCommerce commerce;

    @Autowired
    JwtCodec jwtCodec;

    @Autowired
    JdbcTemplate jdbc;

    @Value("${resolveflow.identity.jwt.secret}")
    String secret;

    @TestConfiguration
    static class StubCommerceConfiguration {

        @Bean
        @Primary
        StubCommerce stubCommerce(RestClient.Builder builder, JwtCodec jwtCodec) {
            return new StubCommerce(builder, jwtCodec);
        }
    }

    @BeforeEach
    void cleanAndReset() {
        // Each test starts from an empty case_db. This is the test container, never a real database:
        // nothing here deletes a volume or a developer's data (docs/engineering.md:64).
        jdbc.execute("DELETE FROM request_idempotency");
        jdbc.execute("DELETE FROM case_timeline");
        jdbc.execute("DELETE FROM active_case_slot");
        jdbc.execute("DELETE FROM case_requested_action");
        jdbc.execute("DELETE FROM aftersale_case");
        commerce.lineVisible = true;
        // The stub is a singleton in a shared context, so what one test observed is still here:
        // a test asserting "Commerce was never asked" has to start from no observation at all.
        commerce.lastPrincipal = null;
        commerce.lastLineId = null;
    }

    private String customerToken() {
        return jwtCodec.issue(
                new AuthenticatedPrincipal("demo-customer", "M-1001", Role.CUSTOMER, "C-2002"), Instant.now());
    }

    private String reviewerToken() {
        return jwtCodec.issue(
                new AuthenticatedPrincipal("demo-reviewer", "M-1001", Role.REVIEWER, null), Instant.now());
    }

    private static Map<String, Object> body(String lineId, String description) {
        return Map.of("line_id", lineId, "description", description, "requested_actions", java.util.List.of("REFUND"));
    }

    private RestTestClient.ResponseSpec post(String token, String key, Object body) {
        RestTestClient.RequestBodySpec request = rest.post().uri("/api/v1/cases");
        if (token != null) {
            request = request.header(HttpHeaders.AUTHORIZATION, "Bearer " + token);
        }
        if (key != null) {
            request = request.header("Idempotency-Key", key);
        }
        return request.contentType(MediaType.APPLICATION_JSON).body(body).exchange();
    }

    private static JsonNode json(String body) {
        return MAPPER.readTree(body);
    }

    @Test
    @DisplayName("a customer opens a case at QUEUED revision 1 and gets its Location")
    void creatingACaseAnswers201WithLocation() {
        String body = post(customerToken(), "key-open-1", body(LINE, "包裹疑似丢失"))
                .expectStatus()
                .isCreated()
                .expectHeader()
                .value(HttpHeaders.LOCATION, location -> assertThat(location).startsWith("/api/v1/cases/"))
                .expectBody(String.class)
                .returnResult()
                .getResponseBody();

        JsonNode created = json(body);
        assertThat(created.properties().stream().map(java.util.Map.Entry::getKey))
                .containsExactlyInAnyOrder("case_id", "status", "input_revision", "version");
        assertThat(created.get("status").stringValue()).isEqualTo("QUEUED");
        assertThat(created.get("input_revision").asInt()).isEqualTo(1);
        assertThat(created.get("version").asLong()).isEqualTo(1L);

        // The case carries the order Commerce reported, not one the caller sent.
        assertThat(jdbc.queryForObject(
                        "SELECT order_id FROM aftersale_case WHERE case_id = ?",
                        String.class,
                        created.get("case_id").stringValue()))
                .isEqualTo(StubCommerce.ORDER);
        assertThat(commerce.lastPrincipal.customerId())
                .as("scope from the token")
                .isEqualTo("C-2002");
        assertThat(commerce.lastLineId).isEqualTo(LINE);

        // The trajectory's first entry is the customer's own words, written with the case itself.
        assertThat(jdbc.queryForObject(
                        "SELECT kind FROM case_timeline WHERE case_id = ? AND sequence = 1",
                        String.class,
                        created.get("case_id").stringValue()))
                .isEqualTo("case.opened");
        assertThat(jdbc.queryForObject(
                        "SELECT detail FROM case_timeline WHERE case_id = ? AND sequence = 1",
                        String.class,
                        created.get("case_id").stringValue()))
                .contains("包裹疑似丢失");
    }

    @Test
    @DisplayName("the same key with the same body replays the stored answer instead of creating again")
    void theSameBodyReplays() {
        String first = post(customerToken(), "key-replay", body(LINE, "同一件事"))
                .expectStatus()
                .isCreated()
                .expectBody(String.class)
                .returnResult()
                .getResponseBody();

        String second = post(customerToken(), "key-replay", body(LINE, "同一件事"))
                .expectStatus()
                .isCreated()
                .expectBody(String.class)
                .returnResult()
                .getResponseBody();

        assertThat(second).isEqualTo(first);
        assertThat(countCases()).isEqualTo(1);
    }

    @Test
    @DisplayName("the same key with a different body is 409 and creates nothing")
    void theSameKeyWithADifferentBodyConflicts() {
        post(customerToken(), "key-conflict", body(LINE, "第一次描述"))
                .expectStatus()
                .isCreated();

        post(customerToken(), "key-conflict", body(LINE, "换了描述"))
                .expectStatus()
                .isEqualTo(409)
                .expectBody(String.class)
                .value(response -> {
                    JsonNode error = json(response);
                    assertThat(error.get("code").stringValue()).isEqualTo("IDEMPOTENCY_CONFLICT");
                    assertThat(error.get("retryable").asBoolean()).isFalse();
                });

        assertThat(countCases()).isEqualTo(1);
    }

    @Test
    @DisplayName("a second case for the same line is 409 CASE_ALREADY_OPEN, a different code from the key conflict")
    void oneActiveCasePerLine() {
        post(customerToken(), "key-line-1", body(LINE, "第一次")).expectStatus().isCreated();

        post(customerToken(), "key-line-2", body(LINE, "第二次"))
                .expectStatus()
                .isEqualTo(409)
                .expectBody(String.class)
                .value(response -> assertThat(json(response).get("code").stringValue())
                        .as("retrying with a new key can never succeed, so it is not an idempotency problem")
                        .isEqualTo("CASE_ALREADY_OPEN"));

        assertThat(countCases()).isEqualTo(1);
    }

    @Test
    @DisplayName("a line outside the caller's scope is 404, and no case is written")
    void anInvisibleLineIsNotFound() {
        commerce.lineVisible = false;

        post(customerToken(), "key-invisible", body(LINE, "不是我的行"))
                .expectStatus()
                .isNotFound()
                .expectBody(String.class)
                .value(response ->
                        assertThat(json(response).get("code").stringValue()).isEqualTo("NOT_FOUND"));

        assertThat(countCases()).isZero();
    }

    @Test
    @DisplayName("merchant staff do not open cases here")
    void merchantStaffCannotOpenACase() {
        post(reviewerToken(), "key-reviewer", body(LINE, "商家代开"))
                .expectStatus()
                .isForbidden()
                .expectBody(String.class)
                .value(response ->
                        assertThat(json(response).get("code").stringValue()).isEqualTo("FORBIDDEN_SCOPE"));

        assertThat(countCases()).isZero();
        assertThat(commerce.lastLineId).as("Commerce is never even asked").isNull();
    }

    @Test
    @DisplayName("the idempotency key is required, and the body must be the documented one")
    void malformedRequestsAreRefused() {
        post(customerToken(), null, body(LINE, "没有幂等键"))
                .expectStatus()
                .isBadRequest()
                .expectBody(String.class)
                .value(response ->
                        assertThat(json(response).get("code").stringValue()).isEqualTo("INVALID_ARGUMENT"));

        post(
                        customerToken(),
                        "key-unknown-member",
                        Map.of(
                                "line_id",
                                LINE,
                                "description",
                                "多了字段",
                                "requested_actions",
                                java.util.List.of("REFUND"),
                                "merchant_id",
                                "M-1002"))
                .expectStatus()
                .isBadRequest();

        assertThat(countCases()).isZero();
    }

    @Test
    @DisplayName("an action core does not represent is 422, not a silent acceptance")
    void anUnrepresentableActionIsSemanticInvalid() {
        for (Object actions : java.util.List.of(
                java.util.List.of("RESHIP"), java.util.List.of(), java.util.List.of("REFUND", "REFUND"))) {
            post(
                            customerToken(),
                            "key-actions-" + actions.hashCode(),
                            Map.of("line_id", LINE, "description", "动作不合法", "requested_actions", actions))
                    .expectStatus()
                    .isEqualTo(422)
                    .expectBody(String.class)
                    .value(response ->
                            assertThat(json(response).get("code").stringValue()).isEqualTo("SEMANTIC_INVALID"));
        }

        assertThat(countCases()).isZero();
    }

    private int countCases() {
        return jdbc.queryForObject("SELECT COUNT(*) FROM aftersale_case", Integer.class);
    }
}
