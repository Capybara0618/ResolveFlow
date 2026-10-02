package com.resolveflow.caseservice.casefile;

import static org.assertj.core.api.Assertions.assertThat;

import com.resolveflow.caseservice.CaseDatabaseTest;
import com.resolveflow.caseservice.policy.PolicyImportService;
import com.resolveflow.caseservice.policy.PolicyRule;
import com.resolveflow.shared.core.CoreEnvelope;
import com.resolveflow.shared.core.CoreFixtures;
import com.resolveflow.shared.security.AuthenticatedPrincipal;
import com.resolveflow.shared.security.JwtCodec;
import com.resolveflow.shared.security.Role;
import java.time.Duration;
import java.time.Instant;
import java.util.Map;
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
import org.springframework.http.MediaType;
import org.springframework.test.web.servlet.client.RestTestClient;
import tools.jackson.databind.JsonNode;
import tools.jackson.databind.ObjectMapper;
import tools.jackson.databind.node.ObjectNode;

/**
 * Consuming an approved authorisation (C05.2a, docs/domain-model.md:36, CI-05).
 *
 * <p>What is under test is the transaction that turns a human decision into money on its way out: the
 * authorisation is spent, the case is executing, exactly one signed command exists, and the event that will
 * carry it exists — or none of those happened. The four claims are checked against the real database rather
 * than against a mock, because the property being tested is that they share one commit.
 *
 * <p>The last test covers the other half of the same boundary: an approval that is cancelled before it is
 * consumed must dispatch nothing, and must stop looking spendable — a case that ended while its authorisation
 * still said {@code APPROVED} would be a row claiming money may be spent on work that no longer exists.
 */
@SpringBootTest(
        webEnvironment = SpringBootTest.WebEnvironment.RANDOM_PORT,
        properties = {
            // The loop is enabled so the test drives the same entry point production does. The interval is put
            // beyond the life of the test so the scheduler cannot consume an authorisation behind the test's
            // back; the first tick runs at startup, when there is nothing approved yet.
            "resolveflow.dispatch.enabled=true",
            "resolveflow.dispatch.poll-interval-ms=3600000"
        })
@AutoConfigureRestTestClient
class AuthorizationConsumptionApiTest extends CaseDatabaseTest {

    private static final ObjectMapper MAPPER = new ObjectMapper();
    private static final String RUN = "d9d9d9d9-6666-4777-8888-dddddddddddd";
    private static final String BUNDLE = "policy-logistics-2026.09";
    private static final String VERSION = "2026.09";
    private static final String MERCHANT = "M-1001";
    private static final String CUSTOMER = "C-2002";

    /** What StubCommerce reports as payable for the demo line: the amount the authorisation fixes. */
    private static final long AMOUNT = 2599L;

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

    @Autowired
    PolicyImportService policies;

    @Autowired
    ExecutionDispatchLoop dispatch;

    @Autowired
    CaseCancellationService cancellations;

    @Value("${resolveflow.identity.jwt.secret}")
    String secret;

    private long lineCounter = 7900;

    @BeforeEach
    void prepare() {
        jdbc.execute("DELETE FROM case_policy_bundle");
        jdbc.execute("DELETE FROM case_policy_manifest");
        jdbc.execute("DELETE FROM policy_rule");
        jdbc.execute("DELETE FROM policy_bundle");
        policies.importDirectory(fixtureDirectory());
        deleteAllCaseData(jdbc);
        commerce.reset();
    }

    private static java.nio.file.Path fixtureDirectory() {
        java.nio.file.Path candidate = java.nio.file.Path.of("").toAbsolutePath();
        for (int level = 0; level < 5 && candidate != null; level++) {
            java.nio.file.Path bundles =
                    candidate.resolve("fixtures").resolve("policies").resolve("bundles");
            if (java.nio.file.Files.isDirectory(bundles)) {
                return bundles;
            }
            candidate = candidate.getParent();
        }
        throw new IllegalStateException("fixtures/policies/bundles not found");
    }

    @Test
    @DisplayName("an approved authorisation becomes exactly one signed command, and the case starts executing")
    void anApprovedAuthorisationBecomesOneCommand() {
        JsonNode authorised = authorisedCase("consumption-core");
        String caseId = authorised.get("case").get("case_id").stringValue();
        String authorizationId =
                authorised.get("authorization").get("authorization_id").stringValue();
        String plannedOperation =
                authorised.get("authorization").get("planned_operation_id").stringValue();
        String payloadHash = authorised.get("authorization").get("payload_hash").stringValue();
        long caseVersion = authorised.get("case").get("version").asLong();

        decide(caseId, reviewer(), "\"" + caseVersion + "\"", authorizationId, 1, "APPROVE", "物流结论与政策一致，证据充分");
        assertThat(caseStatus(caseId)).isEqualTo("AUTHORIZED");
        assertThat(jdbc.queryForObject("SELECT COUNT(*) FROM event_outbox", Integer.class))
                .as("approving is not dispatching: no command exists yet")
                .isZero();

        ExecutionDispatchLoop.Pass pass = dispatch.dispatchDue(50);

        assertThat(pass.dispatched())
                .as("the approved authorisation was consumed")
                .isEqualTo(1);
        assertThat(pass.failed()).isZero();

        // The two state machines, in the database rather than in the response bodies.
        assertThat(caseStatus(caseId)).isEqualTo("EXECUTING");
        assertThat(jdbc.queryForObject("SELECT version FROM aftersale_case WHERE case_id = ?", Long.class, caseId))
                .as("consumption moves the case version once")
                .isEqualTo(caseVersion + 2);
        assertThat(authorizationColumn(caseId, "status")).isEqualTo("CONSUMED");
        assertThat(jdbc.queryForObject(
                        "SELECT authorization_version FROM case_authorization WHERE case_id = ?", Long.class, caseId))
                .as("consumption moves the version it was approved at, so a second dispatch cannot match")
                .isEqualTo(3L);
        assertThat(authorizationColumn(caseId, "decision_reason"))
                .as("CONSUMED still has to carry the decision that allowed it to be spent")
                .contains("物流结论与政策一致");
        assertThat(authorizationColumn(caseId, "decided_by")).isEqualTo("demo-reviewer");

        // Exactly one command, keyed by the authorisation, over the operation that was fixed before approval.
        assertThat(jdbc.queryForObject(
                        "SELECT COUNT(*) FROM case_execution_command WHERE case_id = ?", Integer.class, caseId))
                .isEqualTo(1);
        assertThat(jdbc.queryForObject(
                        "SELECT operation_id FROM case_execution_command WHERE authorization_id = ?",
                        String.class,
                        authorizationId))
                .isEqualTo(plannedOperation);

        // The event that will carry it: one outbox row, signed, and carrying what was approved.
        String eventId = jdbc.queryForObject(
                "SELECT event_id FROM case_execution_command WHERE authorization_id = ?",
                String.class,
                authorizationId);
        assertThat(jdbc.queryForObject("SELECT status FROM event_outbox WHERE event_id = ?", String.class, eventId))
                .as("written, not yet handed to the transport")
                .isEqualTo("PENDING");
        assertThat(jdbc.queryForObject("SELECT topic FROM event_outbox WHERE event_id = ?", String.class, eventId))
                .isEqualTo("rf.case.core.v2");

        JsonNode envelope = MAPPER.readTree(outboxEnvelope(eventId));
        assertThat(envelope.get("event_type").stringValue()).isEqualTo("RefundRequested");
        assertThat(envelope.get("causation_id").stringValue())
                .as("the command names the authorisation it came from")
                .isEqualTo(authorizationId);
        JsonNode payload = envelope.get("payload");
        assertThat(payload.get("payload_hash").stringValue())
                .as("the command carries the payload the human approved")
                .isEqualTo(payloadHash);
        assertThat(payload.get("amount_minor").asLong())
                .as("the amount is the one this service recomputed from Commerce's line, not the run's suggestion")
                .isEqualTo(AMOUNT);
        assertThat(payload.get("operation_id").stringValue()).isEqualTo(plannedOperation);
        assertThat(payload.get("authorization_id").stringValue()).isEqualTo(authorizationId);
        assertThat(payload.get("case_id").stringValue()).isEqualTo(caseId);
        assertThat(payload.get("target_service").stringValue()).isEqualTo("commerce-service");
        assertThat(payload.size())
                .as("thirteen members, the twelve plus the hash")
                .isEqualTo(13);

        // The consumer verifies exactly this document (C05.1b); verifying it here is what makes "signed" a
        // claim about the stored bytes rather than about a column being non-empty.
        CoreEnvelope.verify(envelope, CoreEnvelope.publicKeyFromSpkiBase64(CoreFixtures.publicKeySpkiBase64()));

        // The trajectory says the money left, and names what to follow next.
        assertThat(timelineCount(caseId, "EXECUTION_UPDATED")).isEqualTo(1);
        String detail = jdbc.queryForObject(
                "SELECT detail FROM case_timeline WHERE case_id = ? AND kind = 'EXECUTION_UPDATED'",
                String.class,
                caseId);
        assertThat(detail)
                .as("the row a person reads names the operation and the event")
                .contains(plannedOperation)
                .contains(eventId)
                .contains("\"case_status\":\"EXECUTING\"");
    }

    @Test
    @DisplayName("a second pass over the same approval sends nothing")
    void aSecondPassSendsNothing() {
        JsonNode authorised = authorisedCase("consumption-idempotent");
        String caseId = authorised.get("case").get("case_id").stringValue();
        String authorizationId =
                authorised.get("authorization").get("authorization_id").stringValue();
        long caseVersion = authorised.get("case").get("version").asLong();
        decide(caseId, reviewer(), "\"" + caseVersion + "\"", authorizationId, 1, "APPROVE", "同意退款");

        assertThat(dispatch.dispatchDue(50).dispatched()).isEqualTo(1);
        long versionAfterDispatch =
                jdbc.queryForObject("SELECT version FROM aftersale_case WHERE case_id = ?", Long.class, caseId);

        ExecutionDispatchLoop.Pass second = dispatch.dispatchDue(50);

        assertThat(second.dispatched())
                .as("a consumed authorisation is not a candidate again")
                .isZero();
        assertThat(second.skipped())
                .as("it is not a skip either: the query does not return it")
                .isZero();
        assertThat(jdbc.queryForObject("SELECT version FROM aftersale_case WHERE case_id = ?", Long.class, caseId))
                .as("nothing moved the second time")
                .isEqualTo(versionAfterDispatch);
        assertThat(jdbc.queryForObject("SELECT COUNT(*) FROM event_outbox", Integer.class))
                .as("no second command was written")
                .isEqualTo(1);
        assertThat(jdbc.queryForObject(
                        "SELECT COUNT(*) FROM case_execution_command WHERE case_id = ?", Integer.class, caseId))
                .isEqualTo(1);
    }

    @org.junit.jupiter.api.RepeatedTest(5)
    @DisplayName("CF5 cancellation and consumption have one linearized winner")
    void cancellationRacesConsumption() throws Exception {
        JsonNode authorised = authorisedCase("cf5-race-" + java.util.UUID.randomUUID());
        String caseId = authorised.get("case").get("case_id").stringValue();
        String authorizationId =
                authorised.get("authorization").get("authorization_id").stringValue();
        long caseVersion = authorised.get("case").get("version").asLong();
        decide(caseId, reviewer(), "\"" + caseVersion + "\"", authorizationId, 1, "APPROVE", "CF5合成审批");
        var principal = new com.resolveflow.shared.security.AuthenticatedPrincipal(
                "cf5-customer", MERCHANT, com.resolveflow.shared.security.Role.CUSTOMER, CUSTOMER);
        var start = new java.util.concurrent.CountDownLatch(1);
        var pool = java.util.concurrent.Executors.newFixedThreadPool(2);
        try {
            var cancel = pool.submit(() -> {
                start.await();
                try {
                    cancellations.cancel(principal, caseId, new ReasonRequest("CF5消费前撤销"));
                    return true;
                } catch (CaseStateConflictException conflict) {
                    return false;
                }
            });
            var consume = pool.submit(() -> {
                start.await();
                return dispatch.dispatchDue(50);
            });
            start.countDown();
            boolean cancelled = cancel.get(30, java.util.concurrent.TimeUnit.SECONDS);
            ExecutionDispatchLoop.Pass pass = consume.get(30, java.util.concurrent.TimeUnit.SECONDS);
            assertThat(pass.failed()).isZero();
            assertThat(caseStatus(caseId)).isEqualTo(cancelled ? "CANCELLED" : "EXECUTING");
            assertThat(authorizationColumn(caseId, "status")).isEqualTo(cancelled ? "REVOKED" : "CONSUMED");
            assertThat(jdbc.queryForObject("SELECT COUNT(*) FROM event_outbox", Integer.class))
                    .isEqualTo(cancelled ? 0 : 1);
            assertThat(jdbc.queryForObject(
                            "SELECT COUNT(*) FROM case_execution_command WHERE case_id = ?", Integer.class, caseId))
                    .isEqualTo(cancelled ? 0 : 1);
            assertThat(pass.dispatched()).isEqualTo(cancelled ? 0 : 1);
        } finally {
            pool.shutdownNow();
        }
    }

    @Test
    @DisplayName("a case cancelled after its approval dispatches nothing, and stops looking spendable")
    void aCancelledApprovalDispatchesNothing() {
        JsonNode authorised = authorisedCase("consumption-cancelled");
        String caseId = authorised.get("case").get("case_id").stringValue();
        String authorizationId =
                authorised.get("authorization").get("authorization_id").stringValue();
        long caseVersion = authorised.get("case").get("version").asLong();
        decide(caseId, reviewer(), "\"" + caseVersion + "\"", authorizationId, 1, "APPROVE", "先批准，再取消");
        assertThat(authorizationColumn(caseId, "status")).isEqualTo("APPROVED");

        rest.post()
                .uri("/api/v1/cases/" + caseId + "/cancel")
                .header("Authorization", "Bearer " + customer())
                .contentType(MediaType.APPLICATION_JSON)
                .body(MAPPER.writeValueAsString(Map.of("reason", "客户不再需要退款")))
                .headers(h -> addReviewHeaders(h, caseId))
                .exchange()
                .expectStatus()
                .isOk();

        assertThat(authorizationColumn(caseId, "status"))
                .as("cancelling is an act, so the approval is withdrawn rather than left alive")
                .isEqualTo("REVOKED");
        assertThat(authorizationColumn(caseId, "decision_reason"))
                .contains("cancelled before the authorisation was consumed");

        ExecutionDispatchLoop.Pass pass = dispatch.dispatchDue(50);

        assertThat(pass.dispatched())
                .as("a cancelled case has no execution edge")
                .isZero();
        assertThat(caseStatus(caseId)).isEqualTo("CANCELLED");
        assertThat(jdbc.queryForObject(
                        "SELECT COUNT(*) FROM case_execution_command WHERE case_id = ?", Integer.class, caseId))
                .isZero();
        assertThat(jdbc.queryForObject("SELECT COUNT(*) FROM event_outbox", Integer.class))
                .as("nothing was sent")
                .isZero();
    }

    @Test
    @DisplayName("a command this service cannot rebuild into the approved payload is not sent")
    void aCommandThatNoLongerMatchesTheApprovedPayloadIsNotSent() {
        JsonNode authorised = authorisedCase("consumption-drifted");
        String caseId = authorised.get("case").get("case_id").stringValue();
        String authorizationId =
                authorised.get("authorization").get("authorization_id").stringValue();
        long caseVersion = authorised.get("case").get("version").asLong();
        decide(caseId, reviewer(), "\"" + caseVersion + "\"", authorizationId, 1, "APPROVE", "同意退款");

        // Reaching this state through the routes is impossible: approval recomputes the hash and lapses an
        // authorisation whose row no longer produces it. The row is drifted here anyway, because the check
        // under test is the last one before money moves, and "the approval already checked" is exactly the
        // assumption a dispatch that pays the wrong amount would be built on.
        jdbc.update(
                "UPDATE case_authorization SET payload_hash = ? WHERE authorization_id = ?",
                "0".repeat(64),
                authorizationId);

        ExecutionDispatchLoop.Pass pass = dispatch.dispatchDue(50);

        assertThat(pass.dispatched()).as("nothing was sent").isZero();
        assertThat(pass.skipped())
                .as("it was refused rather than retried: the row cannot become right")
                .isEqualTo(1);
        assertThat(jdbc.queryForObject("SELECT COUNT(*) FROM event_outbox", Integer.class))
                .isZero();
        assertThat(jdbc.queryForObject(
                        "SELECT COUNT(*) FROM case_execution_command WHERE case_id = ?", Integer.class, caseId))
                .isZero();
        assertThat(caseStatus(caseId))
                .as("a refusal mid-transaction rolls the whole dispatch back")
                .isEqualTo("AUTHORIZED");
        assertThat(authorizationColumn(caseId, "status")).isEqualTo("APPROVED");
    }

    private String token(String subject, Role role, String customerId) {
        return new JwtCodec(secret, Duration.ofHours(1))
                .issue(new AuthenticatedPrincipal(subject, MERCHANT, role, customerId), Instant.now());
    }

    private String serviceToken() {
        return new JwtCodec(secret, Duration.ofHours(1)).issueServiceToken("agent-service", Instant.now());
    }

    private String reviewer() {
        return token("demo-reviewer", Role.REVIEWER, null);
    }

    private String customer() {
        return token("demo-customer", Role.CUSTOMER, CUSTOMER);
    }

    private String openCase() {
        String lineId = String.valueOf(++lineCounter);
        String body = rest.post()
                .uri("/api/v1/cases")
                .header("Authorization", "Bearer " + customer())
                .header("Idempotency-Key", "consumption-case-" + lineId)
                .contentType(MediaType.APPLICATION_JSON)
                .body("{\"line_id\":\"" + lineId + "\",\"description\":\"退款诉求\",\"requested_actions\":[\"REFUND\"]}")
                .exchange()
                .expectStatus()
                .isCreated()
                .expectBody(String.class)
                .returnResult()
                .getResponseBody();
        String openedCase = MAPPER.readTree(body).get("case_id").stringValue();
        claimTestCase(openedCase);
        return openedCase;
    }

    private ObjectNode citation() {
        return jdbc.query(
                "SELECT position, rule_id, title, text FROM policy_rule WHERE bundle_id = ? AND rule_id = ?",
                resultSet -> {
                    assertThat(resultSet.next()).isTrue();
                    PolicyRule rule = PolicyRule.from(
                            BUNDLE,
                            resultSet.getInt("position"),
                            resultSet.getString("rule_id"),
                            resultSet.getString("title"),
                            resultSet.getString("text"));
                    ObjectNode node = MAPPER.createObjectNode();
                    node.put("bundle_id", BUNDLE);
                    node.put("version", VERSION);
                    node.put("rule_id", "R-LOST-001");
                    node.put("chunk_id", rule.chunkId());
                    node.put("content_hash", rule.contentHash());
                    return node;
                },
                BUNDLE,
                "R-LOST-001");
    }

    /** Open a case and deliver a proposal the re-check validates, so an authorisation exists to approve. */
    private JsonNode authorisedCase(String callbackId) {
        String caseId = openCase();
        ObjectNode proposal = MAPPER.createObjectNode();
        proposal.put("schema_version", 2);
        proposal.put("proposal_id", java.util.UUID.randomUUID().toString());
        proposal.put("run_id", RUN);
        proposal.put("case_id", caseId);
        proposal.put("input_revision", 1);
        proposal.put("case_type", "LOGISTICS");
        proposal.put("recommended_action", "REFUND");
        proposal.put("summary", "承运商判定丢失，按 2026.09 政策全额退款");
        proposal.put("suggested_amount_minor", 2000);
        proposal.putArray("reason_codes").add("CARRIER_LOST");
        proposal.putArray("policy_refs").add(citation());

        ObjectNode body = MAPPER.createObjectNode();
        body.put("callback_id", callbackId);
        body.put("run_id", RUN);
        body.put("input_revision", 1);
        body.put("kind", "PROPOSAL");
        body.set("payload", proposal);
        body.put("traceparent", "00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01");
        rest.post()
                .uri("/internal/v1/cases/" + caseId + "/agent-callbacks")
                .header("Authorization", "Bearer " + serviceToken())
                .contentType(MediaType.APPLICATION_JSON)
                .body(body.toString())
                .exchange()
                .expectStatus()
                .isOk();

        return view(caseId, reviewer());
    }

    private JsonNode view(String caseId, String token) {
        String body = rest.get()
                .uri("/api/v1/cases/" + caseId)
                .header("Authorization", "Bearer " + token)
                .exchange()
                .expectStatus()
                .isOk()
                .expectBody(String.class)
                .returnResult()
                .getResponseBody();
        return MAPPER.readTree(body);
    }

    private JsonNode decide(
            String caseId,
            String token,
            String ifMatch,
            String authorizationId,
            long version,
            String decision,
            String reason) {
        ObjectNode body = MAPPER.createObjectNode();
        body.put("authorization_id", authorizationId);
        body.put("authorization_version", version);
        body.put("decision", decision);
        body.put("reason", reason);
        return MAPPER.readTree(rest.post()
                .uri("/api/v1/cases/" + caseId + "/reviews")
                .header("Authorization", "Bearer " + token)
                .header("If-Match", ifMatch)
                .contentType(MediaType.APPLICATION_JSON)
                .body(body.toString())
                .headers(h -> addCollaborationHeader(h, caseId))
                .exchange()
                .expectStatus()
                .isOk()
                .expectBody(String.class)
                .returnResult()
                .getResponseBody());
    }

    private String authorizationColumn(String caseId, String column) {
        return jdbc.queryForObject(
                "SELECT " + column + " FROM case_authorization WHERE case_id = ?", String.class, caseId);
    }

    private String caseStatus(String caseId) {
        return jdbc.queryForObject("SELECT status FROM aftersale_case WHERE case_id = ?", String.class, caseId);
    }

    private int timelineCount(String caseId, String kind) {
        return jdbc.queryForObject(
                "SELECT COUNT(*) FROM case_timeline WHERE case_id = ? AND kind = ?", Integer.class, caseId, kind);
    }

    private String outboxEnvelope(String eventId) {
        return jdbc.queryForObject("SELECT envelope FROM event_outbox WHERE event_id = ?", String.class, eventId);
    }
}
