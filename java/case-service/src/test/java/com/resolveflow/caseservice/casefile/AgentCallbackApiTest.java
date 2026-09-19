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
import tools.jackson.databind.node.ArrayNode;
import tools.jackson.databind.node.ObjectNode;

/**
 * What a run may tell a case, and what happens to a delivery that no longer applies
 * (docs/core-contracts.md:59).
 *
 * <p>The properties under test are the sentences the contract uses about callbacks: a redelivery is a
 * DUPLICATE rather than a second effect, an old revision is STALE rather than applied, a late STARTED does not
 * roll the state back, and after a human takes over the run is told STALE instead of being obeyed. Each of
 * those is asserted against the database and against the case view the user reads, because a disposition the
 * response claims and the case does not show would be a promise with nothing behind it.
 */
@SpringBootTest(webEnvironment = SpringBootTest.WebEnvironment.RANDOM_PORT)
@AutoConfigureRestTestClient
class AgentCallbackApiTest extends CaseDatabaseTest {

    private static final ObjectMapper MAPPER = new ObjectMapper();
    private static final String RUN = "e2e2e2e2-3333-4444-8555-aaaaaaaaaaaa";
    private static final String STARTED_AT = "2026-09-19T02:00:00Z";

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

    private long lineCounter = 7300;

    @BeforeEach
    void prepare() {
        deleteAllCaseData(jdbc);
        commerce.lineVisible = true;
    }

    private String serviceToken() {
        return new JwtCodec(secret, Duration.ofHours(1)).issueServiceToken("agent-service", Instant.now());
    }

    private String userToken() {
        return new JwtCodec(secret, Duration.ofHours(1))
                .issue(new AuthenticatedPrincipal("demo-customer", "M-1001", Role.CUSTOMER, "C-2002"), Instant.now());
    }

    /** Opens a case and returns its id. */
    private String openCase() {
        String body = rest.post()
                .uri("/api/v1/cases")
                .header("Authorization", "Bearer " + userToken())
                .header("Idempotency-Key", "callback-case-" + (++lineCounter))
                .contentType(org.springframework.http.MediaType.APPLICATION_JSON)
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

    private ObjectNode startedPayload() {
        ObjectNode payload = MAPPER.createObjectNode();
        payload.put("started_at", STARTED_AT);
        return payload;
    }

    private ObjectNode questionPayload(String questionId) {
        ObjectNode payload = MAPPER.createObjectNode();
        payload.put("question_id", questionId);
        ArrayNode questions = payload.putArray("questions");
        for (String field : new String[] {"tracking_number", "package_photo"}) {
            ObjectNode question = questions.addObject();
            question.put("field", field);
            question.put("prompt", "请补充 " + field);
        }
        payload.putArray("reason_codes").add("NEED_TRACKING");
        return payload;
    }

    private ObjectNode failurePayload(boolean retryable) {
        ObjectNode payload = MAPPER.createObjectNode();
        payload.putArray("reason_codes").add("TOOL_TIMEOUT");
        payload.put("retryable", retryable);
        return payload;
    }

    private ObjectNode envelope(String callbackId, int revision, String kind, JsonNode payload) {
        ObjectNode body = MAPPER.createObjectNode();
        body.put("callback_id", callbackId);
        body.put("run_id", RUN);
        body.put("input_revision", revision);
        body.put("kind", kind);
        body.set("payload", payload);
        body.put("traceparent", "00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01");
        return body;
    }

    /** Posts a delivery and returns the parsed response. */
    private JsonNode deliver(String caseId, ObjectNode body) {
        String response = rest.post()
                .uri("/internal/v1/cases/" + caseId + "/agent-callbacks")
                .header("Authorization", "Bearer " + serviceToken())
                .contentType(org.springframework.http.MediaType.APPLICATION_JSON)
                .body(body.toString())
                .exchange()
                .expectStatus()
                .isOk()
                .expectBody(String.class)
                .returnResult()
                .getResponseBody();
        return MAPPER.readTree(response);
    }

    private org.springframework.test.web.servlet.client.RestTestClient.ResponseSpec deliverExpecting(
            String caseId, ObjectNode body, int status) {
        return rest.post()
                .uri("/internal/v1/cases/" + caseId + "/agent-callbacks")
                .header("Authorization", "Bearer " + serviceToken())
                .contentType(org.springframework.http.MediaType.APPLICATION_JSON)
                .body(body.toString())
                .exchange()
                .expectStatus()
                .isEqualTo(status);
    }

    private String status(String caseId) {
        return jdbc.queryForObject("SELECT status FROM aftersale_case WHERE case_id = ?", String.class, caseId);
    }

    private long version(String caseId) {
        return jdbc.queryForObject("SELECT version FROM aftersale_case WHERE case_id = ?", Long.class, caseId);
    }

    private int revision(String caseId) {
        return jdbc.queryForObject(
                "SELECT input_revision FROM aftersale_case WHERE case_id = ?", Integer.class, caseId);
    }

    private int timelineCount(String caseId, String kind) {
        return jdbc.queryForObject(
                "SELECT COUNT(*) FROM case_timeline WHERE case_id = ? AND kind = ?", Integer.class, caseId, kind);
    }

    private int inboxCount(String caseId) {
        return jdbc.queryForObject("SELECT COUNT(*) FROM agent_callback WHERE case_id = ?", Integer.class, caseId);
    }

    private String inboxDisposition(String callbackId) {
        return jdbc.queryForObject(
                "SELECT disposition FROM agent_callback WHERE callback_id = ?", String.class, callbackId);
    }

    /** The trajectory the user reads, as sentences. */
    private java.util.List<String> trajectory(String caseId) {
        String body = rest.get()
                .uri("/api/v1/cases/" + caseId)
                .header("Authorization", "Bearer " + userToken())
                .exchange()
                .expectStatus()
                .isOk()
                .expectBody(String.class)
                .returnResult()
                .getResponseBody();
        java.util.List<String> sentences = new java.util.ArrayList<>();
        MAPPER.readTree(body)
                .get("timeline")
                .forEach(event -> sentences.add(event.get("summary").stringValue()));
        return sentences;
    }

    /** The customer answering, which is what moves the revision and lets a run resume. */
    private void appendEvidence(String caseId) {
        rest.post()
                .uri("/api/v1/cases/" + caseId + "/evidence")
                .header("Authorization", "Bearer " + userToken())
                .contentType(org.springframework.http.MediaType.APPLICATION_JSON)
                .body("{\"text\":\"运单号 SF123456789\",\"evidence_kind\":\"CUSTOMER_STATEMENT\"}")
                .exchange()
                .expectStatus()
                .isOk();
    }

    @Test
    @DisplayName("an accepted STARTED moves the case into investigation and shows in the trajectory")
    void theRunIsAcceptedAndTheCaseStartsInvestigating() {
        String caseId = openCase();

        JsonNode response = deliver(caseId, envelope("cb-started-1", 1, "STARTED", startedPayload()));

        assertThat(response.get("disposition").stringValue()).isEqualTo("ACCEPTED");
        assertThat(response.get("case_version").asLong()).isEqualTo(2);
        assertThat(status(caseId)).isEqualTo("ANALYZING");
        assertThat(timelineCount(caseId, "AGENT_STARTED")).isEqualTo(1);
        assertThat(inboxDisposition("cb-started-1")).isEqualTo("ACCEPTED");
        assertThat(trajectory(caseId)).contains("调查已受理");
    }

    @Test
    @DisplayName("an identical redelivery is a DUPLICATE that applies nothing a second time")
    void anIdenticalRedeliveryAppliesNothingTwice() {
        String caseId = openCase();
        ObjectNode delivery = envelope("cb-started-2", 1, "STARTED", startedPayload());
        deliver(caseId, delivery);
        long afterFirst = version(caseId);

        JsonNode second = deliver(caseId, delivery);

        assertThat(second.get("disposition").stringValue()).isEqualTo("DUPLICATE");
        assertThat(second.has("case_version"))
                .as("no version came from a delivery that applied nothing")
                .isFalse();
        assertThat(version(caseId)).isEqualTo(afterFirst);
        assertThat(timelineCount(caseId, "AGENT_STARTED")).isEqualTo(1);
        assertThat(inboxCount(caseId)).isEqualTo(1);
    }

    @Test
    @DisplayName("the same callback_id with different content is a conflict, not a redelivery")
    void theSameCallbackIdWithDifferentContentIsARefusal() {
        String caseId = openCase();
        deliver(caseId, envelope("cb-reused", 1, "STARTED", startedPayload()));

        ObjectNode different = envelope("cb-reused", 1, "FAILED", failurePayload(true));
        deliverExpecting(caseId, different, 409).expectBody(String.class).value(body -> {
            JsonNode json = MAPPER.readTree(body);
            assertThat(json.get("code").stringValue()).isEqualTo("IDEMPOTENCY_CONFLICT");
            assertThat(json.get("message").stringValue()).contains("cb-reused");
        });
        assertThat(status(caseId))
                .as("the refused delivery changed nothing, in particular not the status a FAILED would set")
                .isEqualTo("ANALYZING");
        assertThat(timelineCount(caseId, "AGENT_FAILED")).isZero();
    }

    @Test
    @DisplayName("a delivery from a revision the case has left is STALE, and is recorded as such")
    void aDeliveryFromAnOlderRevisionIsStale() {
        String caseId = openCase();
        deliver(caseId, envelope("cb-started-3", 1, "STARTED", startedPayload()));
        appendEvidence(caseId);
        assertThat(revision(caseId)).isEqualTo(2);
        long afterEvidence = version(caseId);

        JsonNode stale = deliver(caseId, envelope("cb-old-revision", 1, "FAILED", failurePayload(true)));

        assertThat(stale.get("disposition").stringValue()).isEqualTo("STALE");
        assertThat(stale.has("case_version")).isFalse();
        assertThat(version(caseId)).isEqualTo(afterEvidence);
        assertThat(status(caseId)).isEqualTo("ANALYZING");
        assertThat(timelineCount(caseId, "AGENT_FAILED")).isZero();
        assertThat(inboxDisposition("cb-old-revision"))
                .as("arrived and did not apply is exactly the fact the record is for")
                .isEqualTo("STALE");
    }

    @Test
    @DisplayName("a revision ahead of the case is a protocol error, not staleness")
    void aRevisionAheadOfTheCaseIsRefused() {
        String caseId = openCase();

        deliverExpecting(caseId, envelope("cb-future", 5, "STARTED", startedPayload()), 422)
                .expectBody(String.class)
                .value(body -> {
                    JsonNode json = MAPPER.readTree(body);
                    assertThat(json.get("code").stringValue()).isEqualTo("SEMANTIC_INVALID");
                    assertThat(json.get("message").stringValue()).contains("ahead of this case");
                });
        assertThat(inboxCount(caseId))
                .as("a delivery that was never valid is not recorded as a delivery that happened")
                .isZero();
        assertThat(status(caseId)).isEqualTo("QUEUED");
    }

    @Test
    @DisplayName("asking is the run's ending, so it happens once per revision and stops a proposal")
    void askingIsTheRunEndingForThatRevision() {
        String caseId = openCase();
        deliver(caseId, envelope("cb-started-4", 1, "STARTED", startedPayload()));

        JsonNode asked = deliver(caseId, envelope("cb-question-1", 1, "QUESTION", questionPayload("q-1")));
        assertThat(asked.get("disposition").stringValue()).isEqualTo("ACCEPTED");
        assertThat(status(caseId)).isEqualTo("WAITING_CUSTOMER");
        assertThat(trajectory(caseId)).contains("需要客户补充说明");

        deliverExpecting(caseId, envelope("cb-question-2", 1, "QUESTION", questionPayload("q-2")), 422)
                .expectBody(String.class)
                .value(body -> assertThat(MAPPER.readTree(body).get("message").stringValue())
                        .contains("already asked the customer"));
        deliverExpecting(caseId, envelope("cb-failed-after-question", 1, "FAILED", failurePayload(true)), 422);
        assertThat(timelineCount(caseId, "QUESTION_REQUIRED")).isEqualTo(1);
    }

    @Test
    @DisplayName("once the customer answers, the run resumes at the new revision")
    void theCustomerAnsweringLetsTheRunResume() {
        String caseId = openCase();
        deliver(caseId, envelope("cb-question-3", 1, "QUESTION", questionPayload("q-3")));
        appendEvidence(caseId);
        assertThat(status(caseId))
                .as("an answer re-queues the case, which is the documented edge out of WAITING_CUSTOMER"
                        + " (docs/domain-model.md:55), so the run has something to resume into")
                .isEqualTo("QUEUED");

        JsonNode resumed = deliver(caseId, envelope("cb-started-resumed", 2, "STARTED", startedPayload()));

        assertThat(resumed.get("disposition").stringValue()).isEqualTo("ACCEPTED");
        assertThat(status(caseId))
                .as("the answer moved the revision, so this STARTED is a resumed run rather than a late one")
                .isEqualTo("ANALYZING");
    }

    @Test
    @DisplayName("a late STARTED is accepted but never rolls the case state back")
    void aLateStartNeverRollsTheStateBack() {
        String caseId = openCase();
        deliver(caseId, envelope("cb-started-5", 1, "STARTED", startedPayload()));
        deliver(caseId, envelope("cb-question-4", 1, "QUESTION", questionPayload("q-4")));
        assertThat(status(caseId)).isEqualTo("WAITING_CUSTOMER");

        JsonNode late = deliver(caseId, envelope("cb-started-late", 1, "STARTED", startedPayload()));

        assertThat(late.get("disposition").stringValue()).isEqualTo("ACCEPTED");
        assertThat(late.get("case_version").asLong())
                .as("a delivery that only appends a trajectory row still moves the version it was appended at")
                .isEqualTo(version(caseId));
        assertThat(status(caseId))
                .as("the case is still waiting for the customer; that fact did not change")
                .isEqualTo("WAITING_CUSTOMER");
        assertThat(timelineCount(caseId, "AGENT_STARTED")).isEqualTo(2);
    }

    @Test
    @DisplayName("a failure that cannot be retried is the handoff to a human, and after it the run is stale")
    void aFailureIsEitherRetriedOrHandedOver() {
        String caseId = openCase();
        deliver(caseId, envelope("cb-started-6", 1, "STARTED", startedPayload()));

        JsonNode retried = deliver(caseId, envelope("cb-failed-retryable", 1, "FAILED", failurePayload(true)));
        assertThat(retried.get("disposition").stringValue()).isEqualTo("ACCEPTED");
        assertThat(status(caseId)).isEqualTo("QUEUED");
        assertThat(trajectory(caseId)).contains("调查失败，将自动重试");

        JsonNode handedOver = deliver(caseId, envelope("cb-failed-final", 1, "FAILED", failurePayload(false)));
        assertThat(handedOver.get("disposition").stringValue()).isEqualTo("ACCEPTED");
        assertThat(status(caseId)).isEqualTo("PENDING_REVIEW");
        assertThat(trajectory(caseId)).contains("调查失败，转人工处理");

        JsonNode afterHandover = deliver(caseId, envelope("cb-started-after", 1, "STARTED", startedPayload()));
        assertThat(afterHandover.get("disposition").stringValue())
                .as("a human has taken the case over, so the run is told to stop")
                .isEqualTo("STALE");
        assertThat(status(caseId)).isEqualTo("PENDING_REVIEW");
    }

    @Test
    @DisplayName("a proposal that does not bind to this case is refused, and leaves nothing behind")
    void aProposalThatDoesNotBindToThisCaseIsRefused() {
        String caseId = openCase();
        ObjectNode proposal = MAPPER.createObjectNode();
        proposal.put("schema_version", 2);
        proposal.put("proposal_id", "5f0f0f0f-1111-4222-8333-444455556666");
        proposal.put("run_id", RUN);
        proposal.put("case_id", java.util.UUID.randomUUID().toString());
        proposal.put("input_revision", 1);
        proposal.put("case_type", "LOGISTICS");
        proposal.put("recommended_action", "REFUND");
        proposal.put("summary", "物流7天无更新且承运商结论为丢失");
        proposal.putArray("reason_codes").add("CARRIER_LOST");

        deliverExpecting(caseId, envelope("cb-proposal-unbound", 1, "PROPOSAL", proposal), 422)
                .expectBody(String.class)
                .value(body -> assertThat(MAPPER.readTree(body).get("message").stringValue())
                        .contains("case_id"));
        assertThat(status(caseId)).isEqualTo("QUEUED");
        assertThat(inboxCount(caseId))
                .as("the check happens before the claim, so a refused body is not even recorded as arrived")
                .isZero();
        assertThat(jdbc.queryForObject("SELECT COUNT(*) FROM case_proposal", Integer.class))
                .isZero();
    }

    @Test
    @DisplayName("the envelope is checked against the contract, member by member")
    void theEnvelopeIsCheckedAgainstTheContract() {
        String caseId = openCase();

        ObjectNode noId = envelope("cb-", 1, "STARTED", startedPayload());
        noId.put("callback_id", "");
        deliverExpecting(caseId, noId, 422)
                .expectBody(String.class)
                .value(body -> assertThat(MAPPER.readTree(body).get("message").stringValue())
                        .contains("callback_id is required"));

        ObjectNode longId = envelope("cb", 1, "STARTED", startedPayload());
        longId.put("callback_id", "x".repeat(65));
        deliverExpecting(caseId, longId, 422)
                .expectBody(String.class)
                .value(body -> assertThat(MAPPER.readTree(body).get("message").stringValue())
                        .contains("at most 64"));

        ObjectNode badRun = envelope("cb-run", 1, "STARTED", startedPayload());
        badRun.put("run_id", "not-a-uuid");
        deliverExpecting(caseId, badRun, 422)
                .expectBody(String.class)
                .value(body -> assertThat(MAPPER.readTree(body).get("message").stringValue())
                        .contains("run_id must be a uuid"));

        ObjectNode badRevision = envelope("cb-rev", 0, "STARTED", startedPayload());
        deliverExpecting(caseId, badRevision, 422);

        ObjectNode badKind = envelope("cb-kind", 1, "SOMETHING", startedPayload());
        deliverExpecting(caseId, badKind, 422)
                .expectBody(String.class)
                .value(body -> assertThat(MAPPER.readTree(body).get("message").stringValue())
                        .contains("kind must be one of"));

        ObjectNode wrongPayload = envelope("cb-wrong", 1, "STARTED", questionPayload("q-x"));
        deliverExpecting(caseId, wrongPayload, 422)
                .expectBody(String.class)
                .value(body -> assertThat(MAPPER.readTree(body).get("message").stringValue())
                        .contains("payload does not match kind STARTED"));

        ObjectNode unknownMember = startedPayload();
        unknownMember.put("extra", "not in the contract");
        deliverExpecting(caseId, envelope("cb-extra", 1, "STARTED", unknownMember), 422);

        ObjectNode badTraceparent = envelope("cb-trace", 1, "STARTED", startedPayload());
        badTraceparent.put("traceparent", "not-a-traceparent");
        deliverExpecting(caseId, badTraceparent, 422);

        ObjectNode envelopeUnknownMember = envelope("cb-envelope", 1, "STARTED", startedPayload());
        envelopeUnknownMember.put("merchant_id", "M-1001");
        deliverExpecting(caseId, envelopeUnknownMember, 400);

        assertThat(inboxCount(caseId))
                .as("none of these reached the inbox: nothing was applied, so nothing is recorded")
                .isZero();
        assertThat(status(caseId)).isEqualTo("QUEUED");
        assertThat(version(caseId)).isEqualTo(1);
    }

    @Test
    @DisplayName("the route is service-only and the case has to exist")
    void theRouteIsServiceOnlyAndTheCaseMustExist() {
        String caseId = openCase();
        ObjectNode body = envelope("cb-service-only", 1, "STARTED", startedPayload());

        rest.post()
                .uri("/internal/v1/cases/" + caseId + "/agent-callbacks")
                .contentType(org.springframework.http.MediaType.APPLICATION_JSON)
                .body(body.toString())
                .exchange()
                .expectStatus()
                .isUnauthorized();

        rest.post()
                .uri("/internal/v1/cases/" + caseId + "/agent-callbacks")
                .header("Authorization", "Bearer " + userToken())
                .contentType(org.springframework.http.MediaType.APPLICATION_JSON)
                .body(body.toString())
                .exchange()
                .expectStatus()
                .isForbidden();

        rest.post()
                .uri("/internal/v1/cases/00000000-0000-4000-8000-00000000dead/agent-callbacks")
                .header("Authorization", "Bearer " + serviceToken())
                .contentType(org.springframework.http.MediaType.APPLICATION_JSON)
                .body(body.toString())
                .exchange()
                .expectStatus()
                .isNotFound();

        assertThat(inboxCount(caseId)).isZero();
    }
}
