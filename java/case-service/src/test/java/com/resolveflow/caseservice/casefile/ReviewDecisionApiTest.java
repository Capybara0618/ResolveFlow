package com.resolveflow.caseservice.casefile;

import static org.assertj.core.api.Assertions.assertThat;

import com.resolveflow.caseservice.CaseDatabaseTest;
import com.resolveflow.caseservice.policy.PolicyImportService;
import com.resolveflow.caseservice.policy.PolicyRule;
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
 * The human decision (C03.3b, docs/core-contracts.md:34).
 *
 * <p>What is under test is that a decision is final, guarded and grounded:
 *
 * <ul>
 *   <li><b>Guarded by two versions.</b> {@code If-Match} is the case the reviewer read and the body carries
 *       the authorisation version; a decision made from either stale reading is refused, and the refusal
 *       changes nothing.
 *   <li><b>Final.</b> The waiting status and the version are part of the UPDATE, so a second decision loses
 *       in the database rather than in a check that could race.
 *   <li><b>Grounded.</b> Approval re-validates: the revision the payload was fixed for, the hash this
 *       service can recompute from its own rows, and Commerce's answer about the line. A failure of the
 *       first two is permanent, so the authorisation lapses and the case stays with a person; a failure of
 *       the third is the world, so nothing lapses.
 * </ul>
 */
@SpringBootTest(webEnvironment = SpringBootTest.WebEnvironment.RANDOM_PORT)
@AutoConfigureRestTestClient
class ReviewDecisionApiTest extends CaseDatabaseTest {

    private static final ObjectMapper MAPPER = new ObjectMapper();
    private static final String BUNDLE = "policy-logistics-2026.09";
    private static final String VERSION = "2026.09";
    private static final String MERCHANT = "M-1001";
    private static final String CUSTOMER = "C-2002";
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
    CaseRepository cases;

    @Value("${resolveflow.identity.jwt.secret}")
    String secret;

    private long lineCounter = 7700;

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
                .header("Idempotency-Key", "decision-case-" + lineId)
                .contentType(MediaType.APPLICATION_JSON)
                .body("{\"line_id\":\"" + lineId + "\",\"description\":\"退款诉求\",\"requested_actions\":[\"REFUND\"]}")
                .exchange()
                .expectStatus()
                .isCreated()
                .expectBody(String.class)
                .returnResult()
                .getResponseBody();
        return MAPPER.readTree(body).get("case_id").stringValue();
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

    /** Open a case and deliver a proposal the re-check validates, so an authorisation exists. */
    private JsonNode authorisedCase(String callbackId) {
        String caseId = openCase();
        deliverProposal(caseId, 1, callbackId);
        return view(caseId, reviewer());
    }

    private JsonNode deliverProposal(String caseId, int inputRevision, String callbackId) {
        String runId = AgentRunId.forRevision(caseId, inputRevision);
        ObjectNode proposal = MAPPER.createObjectNode();
        proposal.put("schema_version", 2);
        proposal.put("proposal_id", java.util.UUID.randomUUID().toString());
        proposal.put("run_id", runId);
        proposal.put("case_id", caseId);
        proposal.put("input_revision", inputRevision);
        proposal.put("case_type", "LOGISTICS");
        proposal.put("recommended_action", "REFUND");
        proposal.put("summary", "承运商判定丢失，按 2026.09 政策全额退款");
        proposal.put("suggested_amount_minor", 2000);
        proposal.putArray("reason_codes").add("CARRIER_LOST");
        proposal.putArray("policy_refs").add(citation());

        ObjectNode body = MAPPER.createObjectNode();
        body.put("callback_id", callbackId);
        body.put("run_id", runId);
        body.put("input_revision", inputRevision);
        body.put("kind", "PROPOSAL");
        body.set("payload", proposal);
        body.put("traceparent", "00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01");
        String response = rest.post()
                .uri("/internal/v1/cases/" + caseId + "/agent-callbacks")
                .header("Authorization", "Bearer " + serviceToken())
                .contentType(MediaType.APPLICATION_JSON)
                .body(body.toString())
                .exchange()
                .expectStatus()
                .isOk()
                .expectBody(String.class)
                .returnResult()
                .getResponseBody();
        return MAPPER.readTree(response);
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
        var request = rest.post()
                .uri("/api/v1/cases/" + caseId + "/reviews")
                .header("Authorization", "Bearer " + token)
                .contentType(MediaType.APPLICATION_JSON);
        if (ifMatch != null) {
            request = request.header("If-Match", ifMatch);
        }
        return MAPPER.readTree(request.body(body.toString())
                .exchange()
                .expectStatus()
                .isOk()
                .expectBody(String.class)
                .returnResult()
                .getResponseBody());
    }

    private int decideStatus(
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
        var request = rest.post()
                .uri("/api/v1/cases/" + caseId + "/reviews")
                .header("Authorization", "Bearer " + token)
                .contentType(MediaType.APPLICATION_JSON);
        if (ifMatch != null) {
            request = request.header("If-Match", ifMatch);
        }
        return request.body(body.toString())
                .exchange()
                .returnResult(String.class)
                .getStatus()
                .value();
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

    @Test
    @DisplayName("an approval is recorded against the version that was read, and the case moves to AUTHORIZED")
    void anApprovalIsRecorded() {
        JsonNode view = authorisedCase("decision-approve");
        String caseId = view.get("case").get("case_id").stringValue();
        String authorizationId =
                view.get("authorization").get("authorization_id").stringValue();
        long caseVersion = view.get("case").get("version").asLong();

        JsonNode response =
                decide(caseId, reviewer(), "\"" + caseVersion + "\"", authorizationId, 1, "APPROVE", "物流结论与政策一致，证据充分");

        assertThat(response.get("status").stringValue()).isEqualTo("APPROVED");
        assertThat(response.get("authorization_version").asLong())
                .as("the decision moves the version it was made from")
                .isEqualTo(2L);
        assertThat(response.get("case_version").asLong()).isEqualTo(caseVersion + 1);

        JsonNode after = view(caseId, reviewer()).get("authorization");
        assertThat(after.get("status").stringValue()).isEqualTo("APPROVED");
        assertThat(after.get("decided_by").stringValue()).isEqualTo("demo-reviewer");
        assertThat(after.get("decided_role").stringValue()).isEqualTo("REVIEWER");
        assertThat(after.get("decision_reason").stringValue()).contains("物流结论与政策一致");
        assertThat(after.has("decided_at")).isTrue();
        assertThat(after.get("payload_hash").stringValue())
                .as("approving does not change what the authorisation would execute")
                .isEqualTo(view.get("authorization").get("payload_hash").stringValue());
        assertThat(caseStatus(caseId)).isEqualTo("AUTHORIZED");
        assertThat(timelineCount(caseId, "AUTHORIZATION_DECIDED")).isEqualTo(1);
    }

    @Test
    @DisplayName("the trajectory says who decided what, in the reviewer's own words")
    void theTrajectorySaysWhoDecidedWhat() {
        JsonNode view = authorisedCase("decision-trajectory");
        String caseId = view.get("case").get("case_id").stringValue();
        String authorizationId =
                view.get("authorization").get("authorization_id").stringValue();
        long caseVersion = view.get("case").get("version").asLong();

        decide(caseId, reviewer(), "\"" + caseVersion + "\"", authorizationId, 1, "APPROVE", "承运商结论与政策一致");

        java.util.List<String> sentences = new java.util.ArrayList<>();
        for (JsonNode event : view(caseId, reviewer()).get("timeline")) {
            if ("AUTHORIZATION_DECIDED".equals(event.get("type").stringValue())) {
                sentences.add(event.get("summary").stringValue());
            }
        }
        assertThat(sentences)
                .as("the sentence carries the actor, the act, the version and the reason, in that order")
                .hasSize(1)
                .allMatch(sentence -> sentence.contains("demo-reviewer")
                        && sentence.contains("批准了退款授权")
                        && sentence.contains("授权版本 2")
                        && sentence.contains("承运商结论与政策一致"));
    }

    @Test
    @DisplayName("a decision made from a stale case reading changes nothing")
    void aStaleCaseReadingIsRefused() {
        JsonNode view = authorisedCase("decision-stale-case");
        String caseId = view.get("case").get("case_id").stringValue();
        String authorizationId =
                view.get("authorization").get("authorization_id").stringValue();
        long caseVersion = view.get("case").get("version").asLong();

        assertThat(decideStatus(
                        caseId, reviewer(), "\"" + (caseVersion - 1) + "\"", authorizationId, 1, "APPROVE", "看过的是旧版本"))
                .isEqualTo(409);
        assertThat(authorizationColumn(caseId, "status")).isEqualTo("PENDING_REVIEW");
        assertThat(authorizationColumn(caseId, "authorization_version")).isEqualTo("1");
        assertThat(caseStatus(caseId)).isEqualTo("PENDING_REVIEW");
        assertThat(decideStatus(caseId, reviewer(), "1", authorizationId, 1, "APPROVE", "没引号"))
                .as("If-Match is a quoted ETag, not a bare number")
                .isEqualTo(422);
    }

    @Test
    @DisplayName("a decision on a version that has moved is refused, and the first decision stands")
    void theSecondDecisionLosesTheRace() {
        JsonNode view = authorisedCase("decision-race");
        String caseId = view.get("case").get("case_id").stringValue();
        String authorizationId =
                view.get("authorization").get("authorization_id").stringValue();
        long caseVersion = view.get("case").get("version").asLong();

        decide(caseId, reviewer(), "\"" + caseVersion + "\"", authorizationId, 1, "APPROVE", "第一次决定");

        // The same reviewer, the same version, a second time: the version and the waiting status are part
        // of the UPDATE, so this cannot be applied however the checks are ordered.
        assertThat(decideStatus(
                        caseId, reviewer(), "\"" + (caseVersion + 1) + "\"", authorizationId, 1, "REJECT", "改主意了"))
                .isEqualTo(409);
        assertThat(authorizationColumn(caseId, "status")).isEqualTo("APPROVED");
        assertThat(authorizationColumn(caseId, "decision_reason")).isEqualTo("第一次决定");
        assertThat(timelineCount(caseId, "AUTHORIZATION_DECIDED")).isEqualTo(1);
    }

    @Test
    @DisplayName("a rejection ends the case, releases the line, and says so twice in the trajectory")
    void aRejectionEndsTheCase() {
        JsonNode view = authorisedCase("decision-reject");
        String caseId = view.get("case").get("case_id").stringValue();
        String authorizationId =
                view.get("authorization").get("authorization_id").stringValue();
        long caseVersion = view.get("case").get("version").asLong();
        String lineId = view.get("case").get("line_id").stringValue();

        JsonNode response =
                decide(caseId, reviewer(), "\"" + caseVersion + "\"", authorizationId, 1, "REJECT", "证据不足以支持丢失结论");

        assertThat(response.get("status").stringValue()).isEqualTo("REJECTED");
        assertThat(caseStatus(caseId)).isEqualTo("CLOSED_REJECTED");
        assertThat(authorizationColumn(caseId, "decision_reason")).isEqualTo("证据不足以支持丢失结论");
        assertThat(jdbc.queryForObject(
                        "SELECT COUNT(*) FROM active_case_slot WHERE line_id = ?", Integer.class, lineId))
                .as("a terminal case does not occupy its line")
                .isZero();
        assertThat(timelineCount(caseId, "CASE_CLOSED")).isEqualTo(1);
        assertThat(timelineCount(caseId, "AUTHORIZATION_DECIDED")).isEqualTo(1);
    }

    @Test
    @DisplayName("asking for material sends the case back to the customer and lapses the authorisation")
    void askingForMaterialSendsTheCaseBack() {
        JsonNode view = authorisedCase("decision-request-info");
        String caseId = view.get("case").get("case_id").stringValue();
        String authorizationId =
                view.get("authorization").get("authorization_id").stringValue();
        long caseVersion = view.get("case").get("version").asLong();

        JsonNode response = decide(
                caseId, reviewer(), "\"" + caseVersion + "\"", authorizationId, 1, "REQUEST_INFO", "请提供承运商的书面丢失证明");

        assertThat(response.get("status").stringValue()).isEqualTo("EXPIRED");
        assertThat(caseStatus(caseId)).isEqualTo("WAITING_CUSTOMER");
        JsonNode after = view(caseId, reviewer()).get("authorization");
        assertThat(after.get("status").stringValue()).isEqualTo("EXPIRED");
        assertThat(after.get("decision_reason").stringValue()).contains("书面丢失证明");
        assertThat(after.get("decided_by").stringValue())
                .as("the person who asked is part of the record, even though nobody refused anything")
                .isEqualTo("demo-reviewer");
        String questionDetail = jdbc.queryForObject(
                "SELECT detail FROM case_timeline WHERE case_id = ? AND kind = 'QUESTION_REQUIRED'",
                String.class,
                caseId);
        JsonNode question = MAPPER.readTree(questionDetail);
        String questionId = question.get("question_id").stringValue();
        assertThat(questionId).isNotBlank();
        assertThat(question.get("questions").get(0).get("prompt").stringValue()).isEqualTo("请提供承运商的书面丢失证明");

        rest.post()
                .uri("/api/v1/cases/" + caseId + "/evidence")
                .header("Authorization", "Bearer " + customer())
                .contentType(MediaType.APPLICATION_JSON)
                .body(Map.of(
                        "question_id", "another-question",
                        "text", "答非所问",
                        "evidence_kind", "CUSTOMER_STATEMENT"))
                .exchange()
                .expectStatus()
                .isEqualTo(422);
        assertThat(jdbc.queryForObject(
                        "SELECT input_revision FROM aftersale_case WHERE case_id = ?", Integer.class, caseId))
                .isEqualTo(1);

        // The customer answers: the revision moves, and the case is the run's again.
        rest.post()
                .uri("/api/v1/cases/" + caseId + "/evidence")
                .header("Authorization", "Bearer " + customer())
                .contentType(MediaType.APPLICATION_JSON)
                .body(Map.of(
                        "question_id", questionId,
                        "text", "承运商书面证明已上传",
                        "evidence_kind", "CUSTOMER_STATEMENT"))
                .exchange()
                .expectStatus()
                .isOk();
        JsonNode answered = view(caseId, reviewer());
        assertThat(answered.get("case").get("input_revision").asInt()).isEqualTo(2);
        assertThat(answered.get("case").get("status").stringValue())
                .as("answering a question puts the case back in the run's hands")
                .isEqualTo("QUEUED");
        assertThat(jdbc.queryForObject(
                        "SELECT question_id FROM case_evidence WHERE case_id = ? AND input_revision = 2",
                        String.class,
                        caseId))
                .isEqualTo(questionId);
        assertThat(jdbc.queryForObject(
                        "SELECT COUNT(*) FROM agent_binding WHERE case_id = ? AND input_revision = 2",
                        Integer.class,
                        caseId))
                .isEqualTo(1);
    }

    @Test
    @DisplayName("the authorization route shares the two-round and expiry guards")
    void requestInfoUsesTheSharedRoundAndExpiryGuards() {
        JsonNode atRoundLimit = authorisedCase("decision-question-limit");
        String limitedCase = atRoundLimit.get("case").get("case_id").stringValue();
        CaseRow limited = cases.findCase(limitedCase);
        for (int round = 1; round <= 2; round++) {
            cases.insertTimeline(
                    limitedCase,
                    java.util.UUID.randomUUID().toString(),
                    cases.nextTimelineSequence(limitedCase),
                    TimelineEventType.QUESTION_REQUIRED.name(),
                    "{\"question_id\":\"prior-" + round + "\"}",
                    Instant.now(),
                    limited.inputRevision());
        }
        assertThat(decideStatus(
                        limitedCase,
                        reviewer(),
                        "\"" + atRoundLimit.get("case").get("version").asLong() + "\"",
                        atRoundLimit
                                .get("authorization")
                                .get("authorization_id")
                                .stringValue(),
                        1,
                        "REQUEST_INFO",
                        "再补一轮"))
                .isEqualTo(409);
        assertThat(authorizationColumn(limitedCase, "status")).isEqualTo("PENDING_REVIEW");

        JsonNode expired = authorisedCase("decision-question-expired");
        String expiredCase = expired.get("case").get("case_id").stringValue();
        jdbc.update(
                "UPDATE aftersale_case SET expires_at = DATE_SUB(NOW(6), INTERVAL 1 SECOND) WHERE case_id = ?",
                expiredCase);
        assertThat(decideStatus(
                        expiredCase,
                        reviewer(),
                        "\"" + expired.get("case").get("version").asLong() + "\"",
                        expired.get("authorization").get("authorization_id").stringValue(),
                        1,
                        "REQUEST_INFO",
                        "超时后补件"))
                .isEqualTo(409);
        assertThat(authorizationColumn(expiredCase, "status")).isEqualTo("PENDING_REVIEW");
    }

    @Test
    @DisplayName("verification creates a new investigation whose proposal replaces the stale one")
    void verificationReinvestigationProducesACurrentProposal() {
        JsonNode original = authorisedCase("decision-reinvestigate-original");
        String caseId = original.get("case").get("case_id").stringValue();
        String oldAuthorization =
                original.get("authorization").get("authorization_id").stringValue();

        rest.post()
                .uri("/api/v1/cases/" + caseId + "/evidence")
                .header("Authorization", "Bearer " + customer())
                .contentType(MediaType.APPLICATION_JSON)
                .body(Map.of("text", "承运商证明包裹未送达", "evidence_kind", "CUSTOMER_STATEMENT"))
                .exchange()
                .expectStatus()
                .isOk();
        String evidenceId = jdbc.queryForObject(
                "SELECT evidence_id FROM case_evidence WHERE case_id = ? AND input_revision = 2", String.class, caseId);
        rest.post()
                .uri("/api/v1/cases/" + caseId + "/reviewed-evidence")
                .header("Authorization", "Bearer " + reviewer())
                .contentType(MediaType.APPLICATION_JSON)
                .body(Map.of(
                        "source_evidence_id", evidenceId,
                        "verification_result", "CONFIRMED",
                        "reason", "已向承运商复核，记录一致"))
                .exchange()
                .expectStatus()
                .isOk();

        JsonNode waiting = view(caseId, reviewer());
        assertThat(waiting.get("case").get("input_revision").asInt()).isEqualTo(3);
        assertThat(waiting.get("case").get("status").stringValue()).isEqualTo("QUEUED");
        assertThat(waiting.get("proposal").get("status").stringValue()).isEqualTo("STALE");
        assertThat(decideStatus(
                        caseId,
                        reviewer(),
                        "\"" + waiting.get("case").get("version").asLong() + "\"",
                        oldAuthorization,
                        1,
                        "APPROVE",
                        "沿用旧审批"))
                .isEqualTo(409);

        JsonNode late = deliverProposal(caseId, 2, "decision-reinvestigate-late");
        assertThat(late.get("disposition").stringValue()).isEqualTo("STALE");
        assertThat(view(caseId, reviewer()).get("case").get("status").stringValue())
                .isEqualTo("QUEUED");

        JsonNode current = deliverProposal(caseId, 3, "decision-reinvestigate-current");
        assertThat(current.get("disposition").stringValue()).isEqualTo("ACCEPTED");
        JsonNode refreshed = view(caseId, reviewer());
        assertThat(refreshed.get("case").get("status").stringValue()).isEqualTo("PENDING_REVIEW");
        assertThat(refreshed.get("proposal").get("input_revision").asInt()).isEqualTo(3);
        assertThat(refreshed.get("proposal").get("status").stringValue()).isEqualTo("VALIDATED");
        assertThat(refreshed.get("authorization").get("input_revision").asInt()).isEqualTo(3);
        assertThat(jdbc.queryForObject("SELECT COUNT(*) FROM case_proposal WHERE case_id = ?", Integer.class, caseId))
                .isEqualTo(2);
    }

    @Test
    @DisplayName("material arriving retires the authorisation, so the approval it was written for is gone")
    void anApprovalAfterTheInputMovedIsRefused() {
        JsonNode view = authorisedCase("decision-input-moved");
        String caseId = view.get("case").get("case_id").stringValue();
        String authorizationId =
                view.get("authorization").get("authorization_id").stringValue();

        rest.post()
                .uri("/api/v1/cases/" + caseId + "/evidence")
                .header("Authorization", "Bearer " + customer())
                .contentType(MediaType.APPLICATION_JSON)
                .body("{\"text\":\"补充说明\",\"evidence_kind\":\"CUSTOMER_STATEMENT\"}")
                .exchange()
                .expectStatus()
                .isOk();
        long caseVersion = view(caseId, reviewer()).get("case").get("version").asLong();

        // C03.3c-2 retired the authorisation in the append's own transaction. C03.3b left it PENDING_REVIEW
        // and let this approval do the lapsing, which meant the case view advertised an approval over input
        // it could never be applied to until somebody tried to use it.
        assertThat(decideStatus(caseId, reviewer(), "\"" + caseVersion + "\"", authorizationId, 1, "APPROVE", "仍然批准"))
                .as("the withdrawal already happened, and a decision on a withdrawn authorisation loses")
                .isEqualTo(409);
        assertThat(caseStatus(caseId))
                .as("a case whose input moved returns to investigation rather than becoming approved")
                .isEqualTo("QUEUED");
        assertThat(authorizationColumn(caseId, "status")).isEqualTo("REVOKED");
        assertThat(authorizationColumn(caseId, "decision_reason"))
                .as("the row says which act retired it, so the next reader is not left guessing")
                .contains("new customer material")
                .contains("revision 2");
    }

    @Test
    @DisplayName("approval is refused, without lapsing anything, when Commerce can no longer pay the line")
    void anApprovalIsRefusedWhenTheLineCannotPay() {
        JsonNode view = authorisedCase("decision-not-payable");
        String caseId = view.get("case").get("case_id").stringValue();
        String authorizationId =
                view.get("authorization").get("authorization_id").stringValue();
        long caseVersion = view.get("case").get("version").asLong();

        commerce.refundedAmount = AMOUNT;

        assertThat(decideStatus(caseId, reviewer(), "\"" + caseVersion + "\"", authorizationId, 1, "APPROVE", "批准"))
                .isEqualTo(409);
        assertThat(authorizationColumn(caseId, "status"))
                .as("the world may change back, so this refusal does not kill the authorisation")
                .isEqualTo("PENDING_REVIEW");
        assertThat(caseStatus(caseId)).isEqualTo("PENDING_REVIEW");
        assertThat(timelineCount(caseId, "AUTHORIZATION_DECIDED")).isZero();
    }

    @Test
    @DisplayName("the customer of the case cannot decide it, and another merchant cannot see it")
    void theDecisionIsStaffOnly() {
        JsonNode view = authorisedCase("decision-scope");
        String caseId = view.get("case").get("case_id").stringValue();
        String authorizationId =
                view.get("authorization").get("authorization_id").stringValue();
        long caseVersion = view.get("case").get("version").asLong();

        assertThat(decideStatus(caseId, customer(), "\"" + caseVersion + "\"", authorizationId, 1, "APPROVE", "我自己批"))
                .as("the party the decision is about does not get to make it")
                .isEqualTo(403);
        String otherMerchant = new JwtCodec(secret, Duration.ofHours(1))
                .issue(new AuthenticatedPrincipal("demo-reviewer-m2", "M-1002", Role.REVIEWER, null), Instant.now());
        assertThat(decideStatus(
                        caseId, otherMerchant, "\"" + caseVersion + "\"", authorizationId, 1, "APPROVE", "别人的单"))
                .isEqualTo(404);
        assertThat(decideStatus(
                        caseId,
                        reviewer(),
                        "\"" + caseVersion + "\"",
                        java.util.UUID.randomUUID().toString(),
                        1,
                        "APPROVE",
                        "没这个授权"))
                .as("an authorisation id that is not this case's is not a decision this route can carry out")
                .isEqualTo(422);
        assertThat(decideStatus(caseId, reviewer(), "\"" + caseVersion + "\"", authorizationId, 1, "MAYBE", "说不清"))
                .isEqualTo(422);
        assertThat(decideStatus(caseId, reviewer(), null, authorizationId, 1, "APPROVE", "不带头"))
                .as("If-Match is required: a decision that read nothing cannot be applied")
                .isEqualTo(422);
    }
}
