package com.resolveflow.caseservice.casefile;

import static org.assertj.core.api.Assertions.assertThat;

import com.resolveflow.caseservice.CaseDatabaseTest;
import com.resolveflow.shared.security.AuthenticatedPrincipal;
import com.resolveflow.shared.security.JwtCodec;
import com.resolveflow.shared.security.Role;
import java.time.Duration;
import java.time.Instant;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.boot.resttestclient.autoconfigure.AutoConfigureRestTestClient;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.boot.test.context.TestConfiguration;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Primary;
import org.springframework.test.web.servlet.client.RestTestClient;
import tools.jackson.databind.JsonNode;
import tools.jackson.databind.ObjectMapper;
import tools.jackson.databind.node.ObjectNode;

/**
 * The reviewer's queue (docs/core-contracts.md:33).
 *
 * <p>The properties under test are the ones a queue gets wrong quietly: it holds the cases a person has to
 * decide and not the ones waiting on the customer, it is scoped by the token rather than by a parameter, a
 * case the merchant cannot see is never in it, and paging does not repeat or skip a case that moved between
 * two pages. The last one is why the cursor is a keyset: rows here got here by being updated.
 */
@SpringBootTest(webEnvironment = SpringBootTest.WebEnvironment.RANDOM_PORT)
@AutoConfigureRestTestClient
class ReviewQueueApiTest extends CaseDatabaseTest {

    private static final ObjectMapper MAPPER = new ObjectMapper();
    private static final String RUN = "c9c9c9c9-5555-4666-8777-cccccccccccc";

    @TestConfiguration
    static class StubCommerceConfiguration {

        @Bean
        @Primary
        StubCommerce commerceStub(
                org.springframework.web.client.RestClient.Builder builder,
                @Value("${resolveflow.identity.jwt.secret}") String secret,
                @Value("${resolveflow.identity.jwt.service-token-ttl:PT1H}") Duration ttl) {
            return new StubCommerce(builder, new JwtCodec(secret, ttl));
        }
    }

    @Autowired
    RestTestClient rest;

    @Autowired
    StubCommerce commerce;

    @Value("${resolveflow.identity.jwt.secret}")
    String secret;

    private long lineCounter = 7600;

    @BeforeEach
    void prepare() {
        deleteAllCaseData(jdbc);
        commerce.reset();
    }

    private String token(String username, String merchantId, Role role, String customerId) {
        return new JwtCodec(secret, Duration.ofHours(1))
                .issue(new AuthenticatedPrincipal(username, merchantId, role, customerId), Instant.now());
    }

    private String serviceToken() {
        return new JwtCodec(secret, Duration.ofHours(1)).issueServiceToken("agent-service", Instant.now());
    }

    /** Opens a case for one merchant's customer and returns its id. */
    private String openCase(String userToken, String merchantId) {
        String lineId = String.valueOf(++lineCounter);
        String body = rest.post()
                .uri("/api/v1/cases")
                .header("Authorization", "Bearer " + userToken)
                .header("Idempotency-Key", "review-case-" + merchantId + "-" + lineId)
                .contentType(org.springframework.http.MediaType.APPLICATION_JSON)
                .body("{\"line_id\":\"" + lineId + "\",\"description\":\"退款诉求\",\"requested_actions\":[\"REFUND\"]}")
                .exchange()
                .expectStatus()
                .isCreated()
                .expectBody(String.class)
                .returnResult()
                .getResponseBody();
        return MAPPER.readTree(body).get("case_id").stringValue();
    }

    /** A non-retryable failure is what hands a case to a person without needing a policy (C03.2b-1). */
    private void handOver(String caseId) {
        ObjectNode payload = MAPPER.createObjectNode();
        payload.putArray("reason_codes").add("TOOL_TIMEOUT");
        payload.put("retryable", false);
        ObjectNode envelope = MAPPER.createObjectNode();
        envelope.put("callback_id", "review-failed-" + caseId);
        envelope.put("run_id", RUN);
        envelope.put("input_revision", 1);
        envelope.put("kind", "FAILED");
        envelope.set("payload", payload);
        envelope.put("traceparent", "00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01");
        rest.post()
                .uri("/internal/v1/cases/" + caseId + "/agent-callbacks")
                .header("Authorization", "Bearer " + serviceToken())
                .contentType(org.springframework.http.MediaType.APPLICATION_JSON)
                .body(envelope.toString())
                .exchange()
                .expectStatus()
                .isOk();
        assertThat(jdbc.queryForObject("SELECT status FROM aftersale_case WHERE case_id = ?", String.class, caseId))
                .as("the handoff has to happen before the queue can be about it")
                .isEqualTo("PENDING_REVIEW");
    }

    private JsonNode queue(String token, String query) {
        String body = rest.get()
                .uri("/api/v1/review/cases" + (query == null ? "" : "?" + query))
                .header("Authorization", "Bearer " + token)
                .exchange()
                .expectStatus()
                .isOk()
                .expectBody(String.class)
                .returnResult()
                .getResponseBody();
        return MAPPER.readTree(body);
    }

    private java.util.List<String> caseIds(JsonNode page) {
        java.util.List<String> ids = new java.util.ArrayList<>();
        page.get("items").forEach(item -> ids.add(item.get("case_id").stringValue()));
        return ids;
    }

    @Test
    @DisplayName("the queue holds the merchant's cases waiting on a person, and only those")
    void theQueueHoldsCasesWaitingOnAPerson() {
        String reviewer = token("demo-reviewer", "M-1001", Role.REVIEWER, null);
        String customer = token("demo-customer", "M-1001", Role.CUSTOMER, "C-2002");

        String queued = openCase(customer, "M-1001");
        String waiting = openCase(customer, "M-1001");
        String handedOver = openCase(customer, "M-1001");
        handOver(handedOver);
        // WAITING_CUSTOMER is the case waiting on the customer, which is not the reviewer's work.
        ObjectNode question = MAPPER.createObjectNode();
        question.put("question_id", "q-1");
        question.putArray("questions")
                .addObject()
                .put("field", "tracking_number")
                .put("prompt", "请补充运单号");
        question.putArray("reason_codes").add("NEED_TRACKING");
        ObjectNode envelope = MAPPER.createObjectNode();
        envelope.put("callback_id", "review-question-" + waiting);
        envelope.put("run_id", RUN);
        envelope.put("input_revision", 1);
        envelope.put("kind", "QUESTION");
        envelope.set("payload", question);
        envelope.put("traceparent", "00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01");
        rest.post()
                .uri("/internal/v1/cases/" + waiting + "/agent-callbacks")
                .header("Authorization", "Bearer " + serviceToken())
                .contentType(org.springframework.http.MediaType.APPLICATION_JSON)
                .body(envelope.toString())
                .exchange()
                .expectStatus()
                .isOk();

        JsonNode page = queue(reviewer, null);

        assertThat(caseIds(page))
                .as("a case waiting on the customer is not a case waiting on the merchant's staff")
                .containsExactly(handedOver);
        assertThat(caseIds(page)).doesNotContain(queued, waiting);
    }

    @Test
    @DisplayName("a queue row carries exactly the members the contract declares")
    void aQueueRowCarriesTheDocumentedMembers() {
        String reviewer = token("demo-reviewer", "M-1001", Role.REVIEWER, null);
        String caseId = openCase(token("demo-customer", "M-1001", Role.CUSTOMER, "C-2002"), "M-1001");
        handOver(caseId);

        JsonNode page = queue(reviewer, null);
        JsonNode item = page.get("items").get(0);

        assertThat(item.properties().stream().map(java.util.Map.Entry::getKey))
                .containsExactlyInAnyOrder(
                        "case_id", "status", "input_revision", "version", "updated_at", "line_id", "requested_actions");
        assertThat(item.get("case_id").stringValue()).isEqualTo(caseId);
        assertThat(item.get("status").stringValue()).isEqualTo("PENDING_REVIEW");
        assertThat(item.get("input_revision").asInt()).isEqualTo(1);
        assertThat(item.get("version").asLong()).isGreaterThan(1L);
        assertThat(item.get("requested_actions").get(0).stringValue()).isEqualTo("REFUND");
        assertThat(item.get("updated_at").stringValue())
                .as("an instant on the wire is UTC with a trailing Z (docs/core-contracts.md:15)")
                .endsWith("Z");
        assertThat(page.get("page").get("limit").asInt()).isEqualTo(20);
        assertThat(page.get("page").has("next_cursor"))
                .as("there is no next page, and one way is kept to say so")
                .isFalse();
    }

    @Test
    @DisplayName("the queue is scoped by the token: another merchant's cases are not there")
    void theQueueIsScopedByTheToken() {
        // The second merchant is M-2002 and not an arbitrary other id, because as of C07.1 opening a case needs a
        // policy version **for that merchant** (PolicySelectionService). Before that, selection ignored the
        // merchant, so this test could use any id and get M-1001's policy — which is also why a second merchant
        // was impossible to onboard. M-2002 is the merchant the shipped fixtures carry a policy set for.
        String reviewerM1 = token("demo-reviewer", "M-1001", Role.REVIEWER, null);
        String reviewerM2 = token("demo-reviewer-m2", "M-2002", Role.REVIEWER, null);
        commerce.lineMerchant = "M-1001";
        String mine = openCase(token("demo-customer", "M-1001", Role.CUSTOMER, "C-2002"), "M-1001");
        commerce.lineMerchant = "M-2002";
        String other = openCase(token("demo-customer-m2", "M-2002", Role.CUSTOMER, "C-2004"), "M-2002");
        handOver(mine);
        handOver(other);

        JsonNode page = queue(reviewerM1, null);

        assertThat(caseIds(page)).containsExactly(mine).doesNotContain(other);
        assertThat(jdbc.queryForObject("SELECT merchant_id FROM aftersale_case WHERE case_id = ?", String.class, other))
                .as("the other case really is another merchant's, not a case that failed to be created")
                .isEqualTo("M-2002");
        assertThat(caseIds(queue(reviewerM2, null)))
                .as("and the other merchant's reviewer sees theirs, not M-1001's")
                .containsExactly(other)
                .doesNotContain(mine);
    }

    @Test
    @DisplayName("a customer has no merchant queue to read, and the answer says so")
    void aCustomerIsRefused() {
        String customer = token("demo-customer", "M-1001", Role.CUSTOMER, "C-2002");

        String body = rest.get()
                .uri("/api/v1/review/cases")
                .header("Authorization", "Bearer " + customer)
                .exchange()
                .expectStatus()
                .isEqualTo(403)
                .expectBody(String.class)
                .returnResult()
                .getResponseBody();

        assertThat(MAPPER.readTree(body).get("code").stringValue()).isEqualTo("FORBIDDEN_SCOPE");
    }

    @Test
    @DisplayName("paging walks the queue once: newest first, no repeats, and it ends")
    void pagingWalksTheQueueOnceWithoutRepeating() {
        String reviewer = token("demo-reviewer", "M-1001", Role.REVIEWER, null);
        String customer = token("demo-customer", "M-1001", Role.CUSTOMER, "C-2002");
        java.util.List<String> handedOver = new java.util.ArrayList<>();
        for (int index = 0; index < 3; index++) {
            String caseId = openCase(customer, "M-1001");
            handOver(caseId);
            handedOver.add(caseId);
            // updated_at has microsecond resolution; without a gap two cases could tie on it.
            jdbc.update(
                    "UPDATE aftersale_case SET updated_at = ? WHERE case_id = ?",
                    java.sql.Timestamp.from(Instant.parse("2026-09-19T0" + (index + 1) + ":00:00Z")),
                    caseId);
        }

        java.util.List<String> walked = new java.util.ArrayList<>();
        String cursor = null;
        for (int page = 0; page < 5; page++) {
            JsonNode response = queue(reviewer, "limit=1" + (cursor == null ? "" : "&cursor=" + cursor));
            walked.addAll(caseIds(response));
            if (!response.get("page").has("next_cursor")) {
                break;
            }
            cursor = response.get("page").get("next_cursor").stringValue();
        }

        assertThat(walked)
                .as("every case exactly once, newest first")
                .containsExactlyElementsOf(java.util.List.of(handedOver.get(2), handedOver.get(1), handedOver.get(0)));
    }

    @Test
    @DisplayName("a cursor this service did not issue, or a limit outside the range, is a client error")
    void aBadPageIsAClientError() {
        String reviewer = token("demo-reviewer", "M-1001", Role.REVIEWER, null);

        for (String query : java.util.List.of("cursor=not-a-cursor", "cursor=" + "YQ", "limit=0", "limit=101")) {
            String body = rest.get()
                    .uri("/api/v1/review/cases?" + query)
                    .header("Authorization", "Bearer " + reviewer)
                    .exchange()
                    .expectStatus()
                    .isEqualTo(400)
                    .expectBody(String.class)
                    .returnResult()
                    .getResponseBody();
            JsonNode error = MAPPER.readTree(body);
            assertThat(error.get("code").stringValue()).isEqualTo("INVALID_ARGUMENT");
            assertThat(error.get("message").stringValue())
                    .as("the caller has to learn what was wrong with the page it asked for")
                    .isNotBlank();
        }

        assertThat(jdbc.queryForObject(
                        "SELECT COUNT(*) FROM aftersale_case WHERE status = 'PENDING_REVIEW'", Integer.class))
                .as("a refused page reads nothing and changes nothing")
                .isZero();
    }
}
