package com.resolveflow.caseservice.casefile;

import static org.assertj.core.api.Assertions.assertThat;

import com.resolveflow.caseservice.CaseDatabaseTest;
import com.resolveflow.shared.security.AuthenticatedPrincipal;
import com.resolveflow.shared.security.JwtCodec;
import com.resolveflow.shared.security.Role;
import java.time.Instant;
import java.util.List;
import java.util.Map;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.Future;
import java.util.concurrent.TimeUnit;
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
 * {@code POST /api/v1/cases/{case_id}/cancel} (docs/domain-model.md:55).
 *
 * <p>Cancellation is the core's first terminal transition, which makes it the first place three separate
 * promises can be checked: the case ends, the line is freed, and the transition is not available twice.
 * The freed line is asserted the only way that means anything — by asking about the same line again and
 * getting a case rather than a refusal.
 */
@AutoConfigureRestTestClient
class CaseCancelApiTest extends CaseDatabaseTest {

    private static final ObjectMapper MAPPER = new ObjectMapper();
    private static final String LINE = "7001";
    private static final String REASON = "客户自行与商家达成一致，不再需要退款";

    @Autowired
    RestTestClient rest;

    @Autowired
    StubCommerce commerce;

    @Autowired
    JwtCodec jwtCodec;

    @Autowired
    JdbcTemplate jdbc;

    @Autowired
    CaseCancellationService cancellations;

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
    }

    private static String token(JwtCodec codec, String user, String merchant, Role role, String customer) {
        return codec.issue(new AuthenticatedPrincipal(user, merchant, role, customer), Instant.now());
    }

    private String customer() {
        return token(jwtCodec, "demo-customer", "M-1001", Role.CUSTOMER, "C-2002");
    }

    private String openCase(String line, String idempotencyKey) {
        String body = rest.post()
                .uri("/api/v1/cases")
                .header(HttpHeaders.AUTHORIZATION, "Bearer " + customer())
                .header("Idempotency-Key", idempotencyKey)
                .contentType(MediaType.APPLICATION_JSON)
                .body(Map.of("line_id", line, "description", "包裹疑似丢失", "requested_actions", List.of("REFUND")))
                .exchange()
                .expectStatus()
                .isCreated()
                .expectBody(String.class)
                .returnResult()
                .getResponseBody();
        return MAPPER.readTree(body).get("case_id").stringValue();
    }

    private String openCase() {
        return openCase(LINE, "cancel-key-" + System.nanoTime());
    }

    private RestTestClient.ResponseSpec cancel(String caseId, String token, Map<String, Object> body) {
        RestTestClient.RequestHeadersSpec<?> request = rest.post()
                .uri("/api/v1/cases/" + caseId + "/cancel")
                .contentType(MediaType.APPLICATION_JSON)
                .body(body);
        if (token != null) {
            request = request.header(HttpHeaders.AUTHORIZATION, "Bearer " + token);
        }
        return request.exchange();
    }

    private Map<String, Object> caseRow(String caseId) {
        return jdbc.queryForMap("SELECT status, version, input_revision FROM aftersale_case WHERE case_id = ?", caseId);
    }

    private int slotCount(String line) {
        return jdbc.queryForObject(
                "SELECT COUNT(*) FROM active_case_slot WHERE merchant_id = 'M-1001' AND line_id = ?",
                Integer.class,
                line);
    }

    @Test
    @DisplayName("cancelling ends the case, records why, and frees the line")
    void cancellingEndsTheCaseAndFreesTheLine() {
        String caseId = openCase();
        assertThat(slotCount(LINE)).as("an active case holds the line").isEqualTo(1);

        String body = cancel(caseId, customer(), Map.of("reason", REASON))
                .expectStatus()
                .isOk()
                .expectBody(String.class)
                .returnResult()
                .getResponseBody();

        JsonNode json = MAPPER.readTree(body);
        assertThat(json.properties().stream().map(Map.Entry::getKey))
                .containsExactlyInAnyOrder("case_id", "status", "version");
        assertThat(json.get("case_id").stringValue()).isEqualTo(caseId);
        assertThat(json.get("status").stringValue()).isEqualTo("CANCELLED");
        assertThat(json.get("version").asLong()).isEqualTo(2);

        Map<String, Object> row = caseRow(caseId);
        assertThat(row.get("status")).isEqualTo("CANCELLED");
        assertThat(row.get("version")).isEqualTo(2L);
        assertThat(row.get("input_revision"))
                .as("cancelling is not new input: the revision the case was decided on stays")
                .isEqualTo(1);

        assertThat(slotCount(LINE))
                .as("a terminal case no longer occupies the line")
                .isZero();

        List<Map<String, Object>> timeline = jdbc.queryForList(
                "SELECT kind, input_revision, detail FROM case_timeline WHERE case_id = ? ORDER BY sequence", caseId);
        assertThat(timeline).hasSize(2);
        assertThat(timeline.get(1).get("kind")).isEqualTo("CASE_CLOSED");
        assertThat(timeline.get(1).get("detail").toString())
                .contains("CANCELLED")
                .contains("cancelled_by");

        String snapshot = rest.get()
                .uri("/api/v1/cases/" + caseId)
                .header(HttpHeaders.AUTHORIZATION, "Bearer " + customer())
                .exchange()
                .expectStatus()
                .isOk()
                .expectBody(String.class)
                .returnResult()
                .getResponseBody();
        JsonNode read = MAPPER.readTree(snapshot);
        assertThat(read.get("case").get("status").stringValue()).isEqualTo("CANCELLED");
        JsonNode closed = read.get("timeline").get(1);
        assertThat(closed.get("type").stringValue()).isEqualTo("CASE_CLOSED");
        assertThat(closed.get("summary").stringValue()).isEqualTo("工单已取消");
    }

    @Test
    @DisplayName("the freed line can be asked about again")
    void theFreedLineCanBeAskedAboutAgain() {
        String first = openCase(LINE, "cancel-reopen-1");
        cancel(first, customer(), Map.of("reason", REASON)).expectStatus().isOk();

        String second = openCase(LINE, "cancel-reopen-2");

        assertThat(second).isNotEqualTo(first);
        assertThat(slotCount(LINE))
                .as("the new case holds the line, and only it")
                .isEqualTo(1);
        assertThat(caseRow(second).get("status")).isEqualTo("QUEUED");
    }

    @Test
    @DisplayName("a terminal case has no further transition")
    void aTerminalCaseHasNoFurtherTransition() {
        String caseId = openCase();
        cancel(caseId, customer(), Map.of("reason", REASON)).expectStatus().isOk();

        cancel(caseId, customer(), Map.of("reason", "再取消一次"))
                .expectStatus()
                .isEqualTo(409)
                .expectBody(String.class)
                .value(body -> assertThat(MAPPER.readTree(body).get("code").stringValue())
                        .isEqualTo("STATE_CONFLICT"));

        assertThat(caseRow(caseId).get("version"))
                .as("a refused cancel must not move the version")
                .isEqualTo(2L);
        assertThat(jdbc.queryForObject(
                        "SELECT COUNT(*) FROM case_timeline WHERE case_id = ? AND kind = 'CASE_CLOSED'",
                        Integer.class,
                        caseId))
                .as("and must not add a second closing event")
                .isEqualTo(1);
    }

    @Test
    @DisplayName("after consumption there is no cancel edge")
    void afterConsumptionThereIsNoCancelEdge() {
        String caseId = openCase();
        // EXECUTING is reachable only after the authorisation is consumed (docs/domain-model.md:55).
        jdbc.update("UPDATE aftersale_case SET status = 'EXECUTING' WHERE case_id = ?", caseId);

        cancel(caseId, customer(), Map.of("reason", REASON))
                .expectStatus()
                .isEqualTo(409)
                .expectBody(String.class)
                .value(body -> assertThat(MAPPER.readTree(body).get("message").stringValue())
                        .contains("no cancel edge after consumption"));

        assertThat(caseRow(caseId).get("status")).isEqualTo("EXECUTING");
        assertThat(slotCount(LINE))
                .as("a refused cancel must not free the line")
                .isEqualTo(1);
    }

    @Test
    @DisplayName("whoever can see the case may cancel it; whoever cannot gets the same 404")
    void visibilityDecidesWhoMayCancel() {
        String caseId = openCase();
        String reviewer = token(jwtCodec, "demo-reviewer", "M-1001", Role.REVIEWER, null);
        String otherCustomer = token(jwtCodec, "demo-customer-2", "M-1001", Role.CUSTOMER, "C-2003");
        String otherMerchant = token(jwtCodec, "demo-reviewer-m2", "M-1002", Role.REVIEWER, null);

        cancel(caseId, otherCustomer, Map.of("reason", REASON)).expectStatus().isNotFound();
        cancel(caseId, otherMerchant, Map.of("reason", REASON)).expectStatus().isNotFound();
        cancel("00000000-0000-4000-8000-00000000dead", customer(), Map.of("reason", REASON))
                .expectStatus()
                .isNotFound();
        cancel(caseId, null, Map.of("reason", REASON))
                .expectStatus()
                .isUnauthorized()
                .expectBody(String.class)
                .value(body -> assertThat(MAPPER.readTree(body).get("code").stringValue())
                        .isEqualTo("UNAUTHENTICATED"));

        assertThat(caseRow(caseId).get("status"))
                .as("none of those attempts changed the case")
                .isEqualTo("QUEUED");

        // The merchant that owns the line can cancel too: the case is its review queue entry.
        cancel(caseId, reviewer, Map.of("reason", "商家侧确认无需退款")).expectStatus().isOk();
        assertThat(caseRow(caseId).get("status")).isEqualTo("CANCELLED");
    }

    @Test
    @DisplayName("a cancel without a usable reason is refused, and the case is untouched")
    void aReasonIsRequired() {
        String caseId = openCase();

        cancel(caseId, customer(), Map.of("reason", "   ")).expectStatus().isEqualTo(422);
        cancel(caseId, customer(), Map.of()).expectStatus().isEqualTo(422);
        cancel(caseId, customer(), Map.of("reason", "x".repeat(501)))
                .expectStatus()
                .isEqualTo(422);

        assertThat(caseRow(caseId).get("status")).isEqualTo("QUEUED");
        assertThat(slotCount(LINE)).isEqualTo(1);
    }

    @Test
    @DisplayName("material cannot be appended to a cancelled case")
    void aCancelledCaseTakesNoMoreMaterial() {
        String caseId = openCase();
        cancel(caseId, customer(), Map.of("reason", REASON)).expectStatus().isOk();

        rest.post()
                .uri("/api/v1/cases/" + caseId + "/evidence")
                .header(HttpHeaders.AUTHORIZATION, "Bearer " + customer())
                .contentType(MediaType.APPLICATION_JSON)
                .body(Map.of("text", "取消之后再补一句", "evidence_kind", "CUSTOMER_STATEMENT"))
                .exchange()
                .expectStatus()
                .isEqualTo(409)
                .expectBody(String.class)
                .value(body -> {
                    JsonNode error = MAPPER.readTree(body);
                    assertThat(error.get("code").stringValue()).isEqualTo("STATE_CONFLICT");
                    // It is cancelled, so the message must not claim it is executing.
                    assertThat(error.get("message").stringValue())
                            .contains("already ended as CANCELLED")
                            .doesNotContain("executing");
                });

        assertThat(jdbc.queryForObject("SELECT COUNT(*) FROM case_evidence WHERE case_id = ?", Integer.class, caseId))
                .isZero();
    }

    @Test
    @DisplayName("two cancels arriving together produce one cancellation")
    void twoCancelsArrivingTogetherProduceOne() throws Exception {
        String caseId = openCase();
        AuthenticatedPrincipal principal =
                new AuthenticatedPrincipal("demo-customer", "M-1001", Role.CUSTOMER, "C-2002");
        ExecutorService pool = Executors.newFixedThreadPool(2);
        var start = new java.util.concurrent.CountDownLatch(1);
        List<Future<Boolean>> futures = new java.util.ArrayList<>();
        for (int i = 0; i < 2; i++) {
            int index = i;
            futures.add(pool.submit(() -> {
                start.await();
                try {
                    cancellations.cancel(principal, caseId, new ReasonRequest("并发取消 " + index));
                    return true;
                } catch (CaseStateConflictException expected) {
                    return false;
                }
            }));
        }
        start.countDown();
        List<Boolean> outcomes = new java.util.ArrayList<>();
        for (Future<Boolean> future : futures) {
            outcomes.add(future.get(30, TimeUnit.SECONDS));
        }
        pool.shutdown();

        assertThat(outcomes).as("exactly one of them cancelled it").containsExactlyInAnyOrder(true, false);
        assertThat(caseRow(caseId).get("version"))
                .as("the version moved once, so one cancellation happened")
                .isEqualTo(2L);
        assertThat(jdbc.queryForObject(
                        "SELECT COUNT(*) FROM case_timeline WHERE case_id = ? AND kind = 'CASE_CLOSED'",
                        Integer.class,
                        caseId))
                .isEqualTo(1);
    }
}
