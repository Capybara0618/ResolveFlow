package com.resolveflow.caseservice.casefile;

import static org.assertj.core.api.Assertions.assertThat;

import com.resolveflow.caseservice.CaseDatabaseTest;
import com.resolveflow.shared.security.AuthenticatedPrincipal;
import com.resolveflow.shared.security.JwtCodec;
import com.resolveflow.shared.security.Role;
import java.time.Duration;
import java.time.Instant;
import java.util.Map;
import java.util.UUID;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.boot.resttestclient.autoconfigure.AutoConfigureRestTestClient;
import org.springframework.boot.test.context.TestConfiguration;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Primary;
import org.springframework.http.MediaType;
import org.springframework.test.web.servlet.client.RestTestClient;
import tools.jackson.databind.JsonNode;
import tools.jackson.databind.ObjectMapper;

/**
 * C06.1c: Case handing a run to the Agent, durably.
 *
 * <p>The three promises this asserts are the ones a case would otherwise silently break:
 *
 * <ol>
 *   <li><b>The binding is written with the case, not after it.</b> {@code agent_binding} is the row that
 *       remembers a run for one {@code (case_id, input_revision)} (docs/domain-model.md:28). A case that
 *       exists without one is a case nothing will ever investigate, and no later read can reconstruct it.
 *   <li><b>The same revision is the same run.</b> The run id is derived from {@code (case_id,
 *       input_revision)}, so a retry after a crash recomputes the same id and the Agent's idempotent
 *       intake answers 202 for the row it already has instead of opening a second run
 *       (contracts/core/openapi-agent.yaml:59).
 *   <li><b>A failed dispatch is retried, not lost.</b> The Agent being down is an outage: the binding
 *       stays PENDING and the next pass tries again. Nothing is rolled back and nothing is dropped.
 * </ol>
 *
 * <p>The Agent is stubbed (like Commerce in these tests) because this is Case's half of the protocol. What
 * the stub records is the request body, and that body is asserted field by field against what the Python
 * Agent's {@code RunRequestShape} requires — a delivery that is right in Java and wrong on the wire looks
 * like an Agent that ignores dispatches.
 */
@AutoConfigureRestTestClient
class AgentRunDispatchApiTest extends CaseDatabaseTest {

    private static final ObjectMapper MAPPER = new ObjectMapper();

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

        /**
         * The Agent, stubbed the same way Commerce is: this module tests Case's half of the protocol, and
         * the real cross-service call is exercised by running both services. {@code @Primary} so the
         * application's own {@link AgentRunClient} is replaced rather than added to.
         */
        @Bean
        @Primary
        StubAgent agentStub(
                org.springframework.web.client.RestClient.Builder builder,
                @Value("${resolveflow.identity.jwt.secret}") String secret,
                @Value("${resolveflow.identity.jwt.service-token-ttl:PT1H}") Duration ttl) {
            return new StubAgent(builder, new JwtCodec(secret, ttl));
        }
    }

    @Autowired
    RestTestClient rest;

    @Autowired
    StubAgent agent;

    @Autowired
    AgentRunBindingRepository bindings;

    @Autowired
    AgentRunDispatch dispatch;

    @Autowired
    JwtCodec jwtCodec;

    @Value("${resolveflow.identity.jwt.secret}")
    String secret;

    private long lineCounter = 7500;

    @BeforeEach
    void prepare() {
        deleteAllCaseData(jdbc);
        agent.reset();
    }

    private String userToken() {
        return jwtCodec.issue(
                new AuthenticatedPrincipal("demo-customer", "M-1001", Role.CUSTOMER, "C-2002"), Instant.now());
    }

    /** Opens a case and returns its id. */
    private String openCase() {
        String body = rest.post()
                .uri("/api/v1/cases")
                .header("Authorization", "Bearer " + userToken())
                .header("Idempotency-Key", "dispatch-case-" + (++lineCounter))
                .contentType(MediaType.APPLICATION_JSON)
                .body("{\"line_id\":\"" + lineCounter + "\",\"description\":\"退款诉求\","
                        + "\"requested_actions\":[\"REFUND\"]}")
                .exchange()
                .expectStatus()
                .isCreated()
                .expectBody(String.class)
                .returnResult()
                .getResponseBody();
        return MAPPER.readTree(body).get("case_id").stringValue();
    }

    // ── the derivation ────────────────────────────────────────────────────────────────────────────

    @Test
    @DisplayName("the run id is derived from (case_id, input_revision), so a retry recomputes the same one")
    void runIdIsDerivedNotGenerated() {
        String caseId = openCase();

        String first = AgentRunId.forRevision(caseId, 1);
        String again = AgentRunId.forRevision(caseId, 1);

        assertThat(first).isEqualTo(again);
        // A v5 (name-based) UUID: the version nibble says how it was made, which is what makes this
        // checkable rather than a convention nobody can verify.
        assertThat(UUID.fromString(first).version()).isEqualTo(5);
        assertThat(first).matches("^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$");
        // A different revision of the same case is a different run.
        assertThat(AgentRunId.forRevision(caseId, 2)).isNotEqualTo(first);
        // And so is a different case.
        assertThat(AgentRunId.forRevision("9c858901-8a57-4791-81fe-4c455b099bc9", 1))
                .isNotEqualTo(first);
    }

    // ── the durable binding ───────────────────────────────────────────────────────────────────────

    @Test
    @DisplayName("opening a case writes the run binding in the same transaction")
    void openingACaseWritesTheBinding() {
        String caseId = openCase();

        Map<String, Object> row = jdbc.queryForMap(
                "SELECT run_id, input_revision, dispatch_status FROM agent_binding WHERE case_id = ?", caseId);
        assertThat(row.get("input_revision")).isEqualTo(1);
        assertThat(row.get("dispatch_status")).isEqualTo("PENDING");
        assertThat(row.get("run_id")).isEqualTo(AgentRunId.forRevision(caseId, 1));
        // (case_id, input_revision) identifies one run: a second row for the same pair cannot exist.
        assertThat(countBindings(caseId)).isEqualTo(1);
    }

    @Test
    @DisplayName("a redelivered create does not write a second binding")
    void replayingACreateDoesNotWriteASecondBinding() {
        String first = openCase();
        String key = "dispatch-replay-1";
        String body = "{\"line_id\":\"7600\",\"description\":\"退款诉求\",\"requested_actions\":[\"REFUND\"]}";

        String created = rest.post()
                .uri("/api/v1/cases")
                .header("Authorization", "Bearer " + userToken())
                .header("Idempotency-Key", key)
                .contentType(MediaType.APPLICATION_JSON)
                .body(body)
                .exchange()
                .expectStatus()
                .isCreated()
                .expectBody(String.class)
                .returnResult()
                .getResponseBody();
        String caseId = MAPPER.readTree(created).get("case_id").stringValue();

        rest.post()
                .uri("/api/v1/cases")
                .header("Authorization", "Bearer " + userToken())
                .header("Idempotency-Key", key)
                .contentType(MediaType.APPLICATION_JSON)
                .body(body)
                .exchange()
                .expectStatus()
                .isCreated();

        assertThat(countBindings(caseId)).isEqualTo(1);
        assertThat(first).isNotNull();
    }

    // ── the dispatch ──────────────────────────────────────────────────────────────────────────────

    @Test
    @DisplayName("a due binding is dispatched, and the Agent is told the run its own contract describes")
    void dispatchSendsTheRunContract() {
        String caseId = openCase();

        AgentRunDispatch.Pass pass = dispatch.dispatchDue(10);

        assertThat(pass.dispatched()).isEqualTo(1);
        assertThat(pass.failed()).isZero();
        assertThat(agent.dispatched).hasSize(1);

        JsonNode sent = agent.dispatched.get(0);
        assertThat(sent.get("run_id").stringValue()).isEqualTo(AgentRunId.forRevision(caseId, 1));
        assertThat(sent.get("case_id").stringValue()).isEqualTo(caseId);
        assertThat(sent.get("input_revision").asInt()).isEqualTo(1);

        JsonNode context = sent.get("context");
        assertThat(context.get("merchant_id").stringValue()).isEqualTo("M-1001");
        assertThat(context.get("customer_id").stringValue()).isEqualTo("C-2002");
        assertThat(context.get("line_id").stringValue()).isNotBlank();
        // order_id must be the uuid Commerce reported, never a blank the Agent would reject.
        assertThat(context.get("order_id").stringValue()).matches("^[0-9a-f-]{36}$");

        JsonNode request = sent.get("request");
        assertThat(request.get("description").stringValue()).isEqualTo("退款诉求");
        assertThat(request.get("requested_actions").size()).isEqualTo(1);
        assertThat(request.get("requested_actions").get(0).stringValue()).isEqualTo("REFUND");
        assertThat(request.has("evidence_refs")).isTrue();

        JsonNode manifest = sent.get("policy_manifest");
        assertThat(manifest.get("bundle_ids").size()).isGreaterThanOrEqualTo(1);
        assertThat(manifest.get("manifest_hash").stringValue()).hasSize(64);
        assertThat(manifest.get("safety_epoch").isNumber()).isTrue();
        // C07.1: the run is dispatched with the merchant its pin was selected for, because that is what it
        // hard-filters retrieval by before ranking anything (docs/policy-rag.md:15).
        assertThat(manifest.get("merchant_id").stringValue())
                .as("the pin names its merchant, and it is the line's own")
                .isEqualTo(context.get("merchant_id").stringValue());

        // The deadline is the submission plus the control-plane window (docs/agent-spec.md:42), and it is
        // an instant the Agent can parse.
        assertThat(sent.get("deadline_at").stringValue()).isNotBlank();
        assertThat(Instant.parse(sent.get("deadline_at").stringValue()))
                .isAfter(Instant.now().minus(Duration.ofMinutes(1)));

        // Every member the Python Agent's RunRequestShape requires is present and none is invented.
        assertThat(sent.propertyNames())
                .containsExactlyInAnyOrder(
                        "run_id",
                        "case_id",
                        "input_revision",
                        "context",
                        "request",
                        "policy_manifest",
                        "deadline_at",
                        "traceparent");
        assertThat(context.propertyNames())
                .containsExactlyInAnyOrder("merchant_id", "customer_id", "order_id", "line_id");
        assertThat(manifest.propertyNames())
                .containsExactlyInAnyOrder("merchant_id", "bundle_ids", "manifest_hash", "safety_epoch");
    }

    @Test
    @DisplayName("a later revision is dispatched with its evidence and a fresh control-plane window")
    void laterRevisionUsesItsOwnInputAndDeadline() {
        String caseId = openCase();
        jdbc.update(
                "UPDATE aftersale_case SET created_at = DATE_SUB(created_at, INTERVAL 1 DAY) WHERE case_id = ?",
                caseId);
        rest.post()
                .uri("/api/v1/cases/" + caseId + "/evidence")
                .header("Authorization", "Bearer " + userToken())
                .contentType(MediaType.APPLICATION_JSON)
                .body("{\"text\":\"承运商证明已补充\",\"evidence_kind\":\"CUSTOMER_STATEMENT\"}")
                .exchange()
                .expectStatus()
                .isOk();
        String evidenceId =
                jdbc.queryForObject("SELECT evidence_id FROM case_evidence WHERE case_id = ?", String.class, caseId);

        AgentRunDispatch.Pass pass = dispatch.dispatchDue(10);

        assertThat(pass.dispatched()).isEqualTo(2);
        JsonNode revised = agent.dispatched.stream()
                .filter(item -> item.get("input_revision").asInt() == 2)
                .findFirst()
                .orElseThrow();
        assertThat(revised.get("run_id").stringValue()).isEqualTo(AgentRunId.forRevision(caseId, 2));
        assertThat(revised.get("request").get("evidence_refs").get(0).stringValue())
                .isEqualTo(evidenceId);
        assertThat(Instant.parse(revised.get("deadline_at").stringValue()))
                .isAfter(Instant.now().plus(Duration.ofMinutes(8)));
    }

    @Test
    @DisplayName("a dispatched binding is not dispatched again")
    void aDispatchedBindingIsNotSentTwice() {
        String caseId = openCase();
        assertThat(dispatch.dispatchDue(10).dispatched()).isEqualTo(1);

        // Nothing is pending any more, so a second pass has no work: a binding that had already been
        // accepted must not be offered to the Agent twice, or its idempotent intake would be the only
        // thing standing between one case revision and two runs.
        AgentRunDispatch.Pass second = dispatch.dispatchDue(10);

        assertThat(second.dispatched()).isZero();
        assertThat(agent.dispatched).hasSize(1);
        assertThat(countBindings(caseId)).isEqualTo(1);
        assertThat(dispatchStatus(caseId)).isEqualTo("DISPATCHED");
        // And the pass found no row at all, rather than finding one and deciding against it.
        assertThat(bindings.findPending(10)).isEmpty();
    }

    @Test
    @DisplayName("the Agent being down leaves the binding due, and the next pass delivers it")
    void anOutageIsRetriedNotLost() {
        String caseId = openCase();
        agent.failNext = true;

        AgentRunDispatch.Pass first = dispatch.dispatchDue(10);

        assertThat(first.dispatched()).isZero();
        assertThat(first.failed()).isEqualTo(1);
        // Still PENDING: an outage must not look like a delivered run, and a run that was never accepted
        // must not be reported as queued.
        assertThat(dispatchStatus(caseId)).isEqualTo("PENDING");

        AgentRunDispatch.Pass second = dispatch.dispatchDue(10);

        assertThat(second.dispatched()).isEqualTo(1);
        assertThat(dispatchStatus(caseId)).isEqualTo("DISPATCHED");
        assertThat(agent.dispatched).hasSize(1);
    }

    @Test
    @DisplayName("the dispatch presents a run:dispatch service token carrying the run's own subjects")
    void theDispatchPresentsAScopedServiceToken() {
        openCase();

        dispatch.dispatchDue(10);

        assertThat(agent.lastToken).isNotNull();
        // Case mints it for itself, and the Agent's verifier requires exactly these claims
        // (agent/src/resolveflow/api/identity.py). A token without them is refused with 422 and the run
        // would be queued for nobody, which is why the scope is asserted here.
        JsonNode claims = MAPPER.readTree(
                java.util.Base64.getUrlDecoder().decode(agent.lastToken.split("\\.")[1]));
        assertThat(claims.get("sub").stringValue()).isEqualTo("case-service");
        assertThat(claims.get("aud").stringValue()).isEqualTo("resolveflow-service");
        assertThat(claims.get("scope").stringValue()).isEqualTo("run:dispatch");
        assertThat(claims.get("merchant_id").stringValue()).isEqualTo("M-1001");
        assertThat(claims.get("customer_id").stringValue()).isEqualTo("C-2002");
    }

    private String dispatchStatus(String caseId) {
        return jdbc.queryForObject("SELECT dispatch_status FROM agent_binding WHERE case_id = ?", String.class, caseId);
    }

    private int countBindings(String caseId) {
        Integer count =
                jdbc.queryForObject("SELECT COUNT(*) FROM agent_binding WHERE case_id = ?", Integer.class, caseId);
        return count == null ? 0 : count;
    }
}
