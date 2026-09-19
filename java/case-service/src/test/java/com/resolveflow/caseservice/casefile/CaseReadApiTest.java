package com.resolveflow.caseservice.casefile;

import static org.assertj.core.api.Assertions.assertThat;

import com.resolveflow.caseservice.CaseDatabaseTest;
import com.resolveflow.shared.security.AuthenticatedPrincipal;
import com.resolveflow.shared.security.JwtCodec;
import com.resolveflow.shared.security.Role;
import java.time.Instant;
import java.util.List;
import java.util.Map;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
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
 * {@code GET /api/v1/cases/{case_id}} (docs/core-contracts.md:29).
 *
 * <p>The case is opened through the real create route and then read back, so the test exercises the
 * trajectory the create transaction actually wrote rather than a row planted by the test. Visibility is
 * the point of most of these: the case's customer, the merchant that owns the line, and nobody else —
 * with "nobody else" and "does not exist" answered identically.
 */
@AutoConfigureRestTestClient
class CaseReadApiTest extends CaseDatabaseTest {

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

    @TestConfiguration
    static class StubCommerceConfiguration {

        @Bean
        @Primary
        StubCommerce stubCommerce(RestClient.Builder builder, JwtCodec jwtCodec) {
            return new StubCommerce(builder, jwtCodec);
        }
    }

    @BeforeEach
    void clean() {
        deleteAllCaseData(jdbc);
        commerce.lineVisible = true;
        commerce.lastPrincipal = null;
        commerce.lastLineId = null;
    }

    private String token(String user, String merchant, Role role, String customer) {
        return jwtCodec.issue(new AuthenticatedPrincipal(user, merchant, role, customer), Instant.now());
    }

    private JsonNode openCase() {
        String body = rest.post()
                .uri("/api/v1/cases")
                .header(
                        HttpHeaders.AUTHORIZATION,
                        "Bearer " + token("demo-customer", "M-1001", Role.CUSTOMER, "C-2002"))
                .header("Idempotency-Key", "read-key-1")
                .contentType(MediaType.APPLICATION_JSON)
                .body(Map.of("line_id", LINE, "description", "包裹疑似丢失", "requested_actions", List.of("REFUND")))
                .exchange()
                .expectStatus()
                .isCreated()
                .expectBody(String.class)
                .returnResult()
                .getResponseBody();
        return MAPPER.readTree(body);
    }

    private RestTestClient.ResponseSpec read(String caseId, String token) {
        RestTestClient.RequestHeadersSpec<?> request = rest.get().uri("/api/v1/cases/" + caseId);
        if (token != null) {
            request = request.header(HttpHeaders.AUTHORIZATION, "Bearer " + token);
        }
        return request.exchange();
    }

    @Test
    @DisplayName("the customer reads their own case with the trajectory the create wrote")
    void theCustomerReadsTheirOwnCase() {
        String caseId = openCase().get("case_id").stringValue();

        String body = read(caseId, token("demo-customer", "M-1001", Role.CUSTOMER, "C-2002"))
                .expectStatus()
                .isOk()
                .expectBody(String.class)
                .returnResult()
                .getResponseBody();

        JsonNode json = MAPPER.readTree(body);
        JsonNode summary = json.get("case");
        assertThat(summary.properties().stream().map(java.util.Map.Entry::getKey))
                .containsExactlyInAnyOrder(
                        "case_id",
                        "status",
                        "input_revision",
                        "version",
                        "created_at",
                        "updated_at",
                        "requested_actions",
                        "line_id");
        assertThat(summary.get("case_id").stringValue()).isEqualTo(caseId);
        assertThat(summary.get("status").stringValue()).isEqualTo("QUEUED");
        assertThat(summary.get("line_id").stringValue()).isEqualTo(LINE);
        assertThat(summary.get("requested_actions").get(0).stringValue()).isEqualTo("REFUND");
        assertThat(summary.get("created_at").stringValue()).endsWith("Z");

        JsonNode event = json.get("timeline").get(0);
        assertThat(event.get("type").stringValue()).isEqualTo("CASE_CREATED");
        assertThat(event.get("event_id").stringValue()).isNotBlank();
        assertThat(event.get("summary").stringValue()).contains(LINE);
        assertThat(event.get("revision").asInt()).isEqualTo(1);
        assertThat(event.get("occurred_at").stringValue()).endsWith("Z");

        // Nothing exists yet for the later steps, so those members are absent rather than null.
        assertThat(json.has("proposal")).isFalse();
        assertThat(json.has("authorization")).isFalse();
        assertThat(json.has("operation")).isFalse();
        assertThat(json.has("evidence")).isFalse();
    }

    @Test
    @DisplayName("the merchant that owns the line reads the case; the review queue needs that")
    void theOwningMerchantReadsTheCase() {
        String caseId = openCase().get("case_id").stringValue();

        read(caseId, token("demo-reviewer", "M-1001", Role.REVIEWER, null))
                .expectStatus()
                .isOk()
                .expectBody(String.class)
                .value(body -> assertThat(
                                MAPPER.readTree(body).get("case").get("case_id").stringValue())
                        .isEqualTo(caseId));
    }

    @Test
    @DisplayName("another customer, another merchant and a stranger all get the same 404")
    void everybodyElseGetsTheSame404() {
        String caseId = openCase().get("case_id").stringValue();

        // Stated as pairs rather than inferred from the token string: a JWT is base64, so looking
        // for a merchant id inside it would silently never match (this test said so itself once).
        record Caller(String who, String token, boolean mayRead) {}
        for (Caller caller : List.of(
                new Caller(
                        "same merchant, different customer",
                        token("demo-customer-2", "M-1001", Role.CUSTOMER, "C-2003"),
                        false),
                new Caller(
                        "another merchant customer",
                        token("demo-customer-m2", "M-1002", Role.CUSTOMER, "C-2004"),
                        false),
                new Caller(
                        "another merchant reviewer", token("demo-reviewer-m2", "M-1002", Role.REVIEWER, null), false),
                new Caller(
                        "owning merchant operator (the review queue is merchant-scoped)",
                        token("demo-operator", "M-1001", Role.OPERATOR, null),
                        true))) {
            int expected = caller.mayRead() ? 200 : 404;
            // The caller is named in the assertion so a failure says who was let in.
            read(caseId, caller.token())
                    .expectStatus()
                    .value(status -> assertThat(status).as(caller.who()).isEqualTo(expected));
        }
    }

    @Test
    @DisplayName("a case that does not exist answers exactly like one that is not yours")
    void unknownCaseIsTheSameAnswer() {
        String missing = "00000000-0000-4000-8000-00000000dead";

        String notMine = read(
                        openCase().get("case_id").stringValue(),
                        token("demo-customer-m2", "M-1002", Role.CUSTOMER, "C-2004"))
                .expectStatus()
                .isNotFound()
                .expectBody(String.class)
                .returnResult()
                .getResponseBody();

        String absent = read(missing, token("demo-customer-m2", "M-1002", Role.CUSTOMER, "C-2004"))
                .expectStatus()
                .isNotFound()
                .expectBody(String.class)
                .returnResult()
                .getResponseBody();

        assertThat(MAPPER.readTree(notMine).get("message").stringValue())
                .isEqualTo(MAPPER.readTree(absent).get("message").stringValue());
    }

    @Test
    @DisplayName("reading a case needs a token, and the trajectory survives a revisit")
    void aTokenIsRequiredAndTheTrajectoryIsStable() {
        String caseId = openCase().get("case_id").stringValue();

        read(caseId, null)
                .expectStatus()
                .isUnauthorized()
                .expectBody(String.class)
                .value(body -> assertThat(MAPPER.readTree(body).get("code").stringValue())
                        .isEqualTo("UNAUTHENTICATED"));

        String customer = token("demo-customer", "M-1001", Role.CUSTOMER, "C-2002");
        String first = read(caseId, customer)
                .expectStatus()
                .isOk()
                .expectBody(String.class)
                .returnResult()
                .getResponseBody();
        String second = read(caseId, customer)
                .expectStatus()
                .isOk()
                .expectBody(String.class)
                .returnResult()
                .getResponseBody();

        assertThat(second)
                .as("the event id is stored, so it does not change between reads")
                .isEqualTo(first);
    }
}
