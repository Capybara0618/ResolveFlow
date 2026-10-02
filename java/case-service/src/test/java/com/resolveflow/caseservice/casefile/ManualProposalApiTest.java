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
import java.util.List;
import java.util.UUID;
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
import tools.jackson.databind.node.ArrayNode;
import tools.jackson.databind.node.ObjectNode;

/**
 * A person's proposal (C03.3c-1, docs/core-contracts.md:36).
 *
 * <p>The properties under test are the three this path decides:
 *
 * <ul>
 *   <li><b>It is new input.</b> Submitting one moves the case's input revision, so the run's proposal and
 *       any authorisation from the previous revision stop applying rather than being reinterpreted.
 *   <li><b>It is checked, and a refusal writes nothing.</b> The same content check a run's proposal goes
 *       through runs here, and because the author is still connected a refusal is answered (422 for a fault
 *       in the submission, 409 when this service's own state says no) instead of being stored.
 *   <li><b>It supersedes a live authorisation.</b> The approval from the previous revision is revoked in the
 *       same transaction that creates its replacement — never left approved over input it was not fixed for.
 * </ul>
 */
@SpringBootTest(webEnvironment = SpringBootTest.WebEnvironment.RANDOM_PORT)
@AutoConfigureRestTestClient
class ManualProposalApiTest extends CaseDatabaseTest {

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

    @Value("${resolveflow.identity.jwt.secret}")
    String secret;

    private long lineCounter = 7800;

    @Test
    void reviewerContextExposesOnlyPinnedPolicyAndRejectsOtherPrincipals() {
        String caseId = openCase();
        String path = "/api/v1/cases/" + caseId + "/review-context";
        String body = rest.get()
                .uri(path)
                .header("Authorization", "Bearer " + reviewer())
                .exchange()
                .expectStatus()
                .isOk()
                .expectBody(String.class)
                .returnResult()
                .getResponseBody();
        JsonNode context = MAPPER.readTree(body);
        assertThat(context.get("policy_rules").toString()).contains("R-LOST-001", BUNDLE, "content_hash");
        assertThat(context.get("allowed_actions").toString()).contains("REJECT", "REQUEST_INFO");
        rest.get()
                .uri(path)
                .header("Authorization", "Bearer " + customer())
                .exchange()
                .expectStatus()
                .isForbidden();
        String outsider = new JwtCodec(secret, Duration.ofHours(1))
                .issue(new AuthenticatedPrincipal("other", "M-9999", Role.REVIEWER, null), Instant.now());
        rest.get()
                .uri(path)
                .header("Authorization", "Bearer " + outsider)
                .exchange()
                .expectStatus()
                .isNotFound();
    }

    private int workspaceAction(String caseId, long version, String action, ObjectNode body) {
        body.put("action", action);
        return rest.post()
                .uri("/api/v1/cases/" + caseId + "/review-actions")
                .header("Authorization", "Bearer " + reviewer())
                .header("If-Match", "\"" + version + "\"")
                .contentType(MediaType.APPLICATION_JSON)
                .body(body.toString())
                .headers(h -> addReviewHeaders(h, caseId))
                .exchange()
                .returnResult(String.class)
                .getStatus()
                .value();
    }

    @Test
    void reviewerCanRejectWithoutAuthorizationButCannotReplayAnOldDecision() {
        String caseId = openCase();
        long version = view(caseId, reviewer()).get("case").get("version").asLong();
        ObjectNode body = MAPPER.createObjectNode().put("reason", "物流材料不支持本次申请");
        assertThat(workspaceAction(caseId, version + 1, "REJECT", body)).isEqualTo(409);
        assertThat(workspaceAction(caseId, version, "REJECT", body)).isEqualTo(200);
        assertThat(view(caseId, reviewer()).get("case").get("status").stringValue())
                .isEqualTo("CLOSED_REJECTED");
        assertThat(count("active_case_slot", caseId)).isZero();
        assertThat(workspaceAction(caseId, version, "REJECT", body)).isEqualTo(409);
    }

    @Test
    void reviewerQuestionWithoutAuthorizationCreatesAQuestionAndPreventsRepeatedAsking() {
        String caseId = openCase();
        long version = view(caseId, reviewer()).get("case").get("version").asLong();
        ObjectNode body = MAPPER.createObjectNode().put("reason", "请补充签收争议说明");
        assertThat(workspaceAction(caseId, version, "REQUEST_INFO", body)).isEqualTo(200);
        JsonNode after = view(caseId, reviewer());
        assertThat(after.get("case").get("status").stringValue()).isEqualTo("WAITING_CUSTOMER");
        assertThat(after.get("case").get("input_revision").asInt()).isEqualTo(2);
        String detail = jdbc.queryForObject(
                "SELECT detail FROM case_timeline WHERE case_id=? AND kind='QUESTION_REQUIRED'", String.class, caseId);
        assertThat(detail).contains("question_id", "请补充签收争议说明");
        assertThat(workspaceAction(caseId, after.get("case").get("version").asLong(), "REQUEST_INFO", body))
                .isEqualTo(409);

        String questionId = MAPPER.readTree(detail).get("question_id").stringValue();
        rest.post()
                .uri("/api/v1/cases/" + caseId + "/evidence")
                .header("Authorization", "Bearer " + customer())
                .contentType(MediaType.APPLICATION_JSON)
                .body(MAPPER.createObjectNode()
                        .put("question_id", questionId)
                        .put("text", "补充签收争议说明")
                        .put("evidence_kind", "CUSTOMER_STATEMENT"))
                .headers(h -> addReviewHeaders(h, caseId))
                .exchange()
                .expectStatus()
                .isOk();
        assertThat(jdbc.queryForObject(
                        "SELECT question_id FROM case_evidence WHERE case_id=? AND input_revision=3",
                        String.class,
                        caseId))
                .isEqualTo(questionId);
        assertThat(jdbc.queryForObject(
                        "SELECT COUNT(*) FROM agent_binding WHERE case_id=? AND input_revision=3",
                        Integer.class,
                        caseId))
                .isEqualTo(1);
    }

    @Test
    void workspaceManualProposalRejectsInventedEvidence() {
        String caseId = openCase();
        long version = view(caseId, reviewer()).get("case").get("version").asLong();
        assertThat(workspaceAction(caseId, version, "MANUAL_PROPOSAL", request("REFUND", "核对后退款")))
                .isEqualTo(422);
        assertThat(count("case_authorization", caseId)).isZero();
    }

    @Test
    void workspaceCreatesAReviewableProposalFromActualCaseEvidence() {
        String caseId = openCase();
        rest.post()
                .uri("/api/v1/cases/" + caseId + "/evidence")
                .header("Authorization", "Bearer " + customer())
                .contentType(MediaType.APPLICATION_JSON)
                .body("{\"text\":\"包裹未收到，请核查物流\",\"evidence_kind\":\"CUSTOMER_STATEMENT\"}")
                .headers(h -> addReviewHeaders(h, caseId))
                .exchange()
                .expectStatus()
                .isOk();
        JsonNode before = view(caseId, reviewer());
        JsonNode material = before.get("evidence").get(0);
        ObjectNode body = request("REFUND", "人工核对物流和材料后建议退款");
        ObjectNode citation = MAPPER.createObjectNode();
        for (String field : List.of("observation_id", "source_ref", "source_version", "content_hash")) {
            citation.put(field, material.get(field).stringValue());
        }
        body.putArray("evidence_refs").add(citation);
        long version = before.get("case").get("version").asLong();
        assertThat(workspaceAction(caseId, version, "MANUAL_PROPOSAL", body)).isEqualTo(200);
        JsonNode after = view(caseId, reviewer());
        assertThat(after.get("authorization").get("status").stringValue()).isEqualTo("PENDING_REVIEW");
        assertThat(after.get("proposal").get("origin").stringValue()).isEqualTo("HUMAN");
        assertThat(workspaceAction(caseId, version, "MANUAL_PROPOSAL", body)).isEqualTo(409);
    }

    @Test
    void workspaceNeverReopensConsumedAuthorization() {
        String caseId = openCase();
        submit(caseId, reviewer(), request("REFUND", "人工核验"));
        JsonNode authorization = view(caseId, reviewer()).get("authorization");
        decide(
                caseId,
                authorization.get("authorization_id").stringValue(),
                authorization.get("authorization_version").asLong(),
                "APPROVE");
        jdbc.update("UPDATE case_authorization SET status='CONSUMED' WHERE case_id=?", caseId);
        long version = view(caseId, reviewer()).get("case").get("version").asLong();
        assertThat(workspaceAction(
                        caseId, version, "REJECT", MAPPER.createObjectNode().put("reason", "改为拒绝")))
                .isEqualTo(409);
    }

    @org.junit.jupiter.params.ParameterizedTest
    @org.junit.jupiter.params.provider.ValueSource(
            strings = {"manual-proposals", "evidence", "reviewed-evidence", "cancel"})
    void consumedInputStaysFrozenWhenTheCaseReturnsToReview(String route) {
        String caseId = openCase();
        submit(caseId, reviewer(), request("REFUND", "人工核验"));
        JsonNode authorization = view(caseId, reviewer()).get("authorization");
        decide(
                caseId,
                authorization.get("authorization_id").stringValue(),
                authorization.get("authorization_version").asLong(),
                "APPROVE");
        jdbc.update("UPDATE case_authorization SET status='CONSUMED' WHERE case_id=?", caseId);
        jdbc.update("UPDATE aftersale_case SET status='PENDING_REVIEW' WHERE case_id=?", caseId);
        long version = view(caseId, reviewer()).get("case").get("version").asLong();
        String revision = column("aftersale_case", "input_revision", caseId);
        ObjectNode body =
                switch (route) {
                    case "manual-proposals" -> request("REFUND", "不能再次形成方案");
                    case "evidence" ->
                        MAPPER.createObjectNode()
                                .put("evidence_kind", "REVIEWER_VERIFICATION")
                                .put("text", "不能改动已消费输入");
                    case "reviewed-evidence" ->
                        MAPPER.createObjectNode()
                                .put("source_evidence_id", UUID.randomUUID().toString())
                                .put("verification_result", "CONFIRMED")
                                .put("reason", "不能再核验");
                    default -> MAPPER.createObjectNode().put("reason", "不能取消已消费工单");
                };
        rest.post()
                .uri("/api/v1/cases/" + caseId + "/" + route)
                .header("Authorization", "Bearer " + reviewer())
                .contentType(MediaType.APPLICATION_JSON)
                .body(body.toString())
                .exchange()
                .expectStatus()
                .isEqualTo(409);
        assertThat(column("aftersale_case", "input_revision", caseId)).isEqualTo(revision);
        assertThat(view(caseId, reviewer()).get("case").get("version").asLong()).isEqualTo(version);
        assertThat(count("case_proposal", caseId)).isEqualTo(1);
        assertThat(column("case_authorization", "status", caseId)).isEqualTo("CONSUMED");
    }

    @BeforeEach
    void prepare() {
        registerTestAccount("other", "M-9999", "REVIEWER", null);
        registerTestAccount("other-reviewer", "M-2002", "REVIEWER", null);
        jdbc.execute("DELETE FROM case_policy_bundle");
        jdbc.execute("DELETE FROM case_policy_manifest");
        jdbc.execute("DELETE FROM policy_rule");
        jdbc.execute("DELETE FROM policy_bundle");
        policies.importDirectory(fixtureDirectory());
        deleteAllCaseData(jdbc);
        commerce.reset();
    }

    @Test
    void investigationEndpointEnforcesStaffAndMerchantScope() {
        String caseId = openCase();
        String path = "/api/v1/cases/" + caseId + "/investigation";
        rest.get()
                .uri(path)
                .header("Authorization", "Bearer " + customer())
                .exchange()
                .expectStatus()
                .isForbidden();
        String other = new JwtCodec(secret, Duration.ofHours(1))
                .issue(new AuthenticatedPrincipal("other-reviewer", "M-2002", Role.REVIEWER, null), Instant.now());
        rest.get()
                .uri(path)
                .header("Authorization", "Bearer " + other)
                .exchange()
                .expectStatus()
                .isNotFound();
        String response = rest.get()
                .uri(path)
                .header("Authorization", "Bearer " + reviewer())
                .exchange()
                .expectStatus()
                .isOk()
                .expectBody(String.class)
                .returnResult()
                .getResponseBody();
        assertThat(MAPPER.readTree(response).get("availability").asText()).isIn("NOT_SCHEDULED", "UNAVAILABLE");
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
                .header("Idempotency-Key", "manual-case-" + lineId)
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

    /** The rule this case's refund leans on, cited the way the fixture hashes it. */
    private ObjectNode policyCitation(String ruleId) {
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
                    node.put("rule_id", ruleId);
                    node.put("chunk_id", rule.chunkId());
                    node.put("content_hash", rule.contentHash());
                    return node;
                },
                BUNDLE,
                ruleId);
    }

    private ObjectNode evidenceCitation() {
        ObjectNode node = MAPPER.createObjectNode();
        node.put("observation_id", UUID.randomUUID().toString());
        node.put("source_ref", "line:7001/shipment");
        node.put("source_version", "2");
        node.put("content_hash", "1".repeat(64));
        return node;
    }

    private ObjectNode request(String action, String reason) {
        ObjectNode body = MAPPER.createObjectNode();
        body.put("action", action);
        ArrayNode evidence = body.putArray("evidence_refs");
        evidence.add(evidenceCitation());
        ArrayNode policy = body.putArray("policy_refs");
        policy.add(policyCitation("R-LOST-001"));
        body.put("reason", reason);
        return body;
    }

    private int submitStatus(String caseId, String token, ObjectNode body) {
        return rest.post()
                .uri("/api/v1/cases/" + caseId + "/manual-proposals")
                .header("Authorization", "Bearer " + token)
                .contentType(MediaType.APPLICATION_JSON)
                .body(body.toString())
                .headers(h -> addReviewHeaders(h, caseId))
                .exchange()
                .returnResult(String.class)
                .getStatus()
                .value();
    }

    private JsonNode submit(String caseId, String token, ObjectNode body) {
        String answer = rest.post()
                .uri("/api/v1/cases/" + caseId + "/manual-proposals")
                .header("Authorization", "Bearer " + token)
                .contentType(MediaType.APPLICATION_JSON)
                .body(body.toString())
                .headers(h -> addReviewHeaders(h, caseId))
                .exchange()
                .expectStatus()
                .isOk()
                .expectBody(String.class)
                .returnResult()
                .getResponseBody();
        return MAPPER.readTree(answer);
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

    private JsonNode decide(String caseId, String authorizationId, long authorisationVersion, String decision) {
        ObjectNode body = MAPPER.createObjectNode();
        body.put("authorization_id", authorizationId);
        body.put("authorization_version", authorisationVersion);
        body.put("decision", decision);
        body.put("reason", "人工复核后" + decision);
        long caseVersion = view(caseId, reviewer()).get("case").get("version").asLong();
        String answer = rest.post()
                .uri("/api/v1/cases/" + caseId + "/reviews")
                .header("Authorization", "Bearer " + reviewer())
                .header("If-Match", "\"" + caseVersion + "\"")
                .contentType(MediaType.APPLICATION_JSON)
                .body(body.toString())
                .headers(h -> addCollaborationHeader(h, caseId))
                .exchange()
                .expectStatus()
                .isOk()
                .expectBody(String.class)
                .returnResult()
                .getResponseBody();
        return MAPPER.readTree(answer);
    }

    private String column(String table, String column, String caseId) {
        return jdbc.queryForObject("SELECT " + column + " FROM " + table + " WHERE case_id = ?", String.class, caseId);
    }

    /**
     * One column of the case's newest authorisation.
     *
     * <p>A case can hold several authorisations — one per revision — and the case view shows the newest, so a
     * test that asked for "the status of the authorisation of this case" would fail on the second revision
     * rather than on the property it meant to check.
     */
    private String newestAuthorization(String column, String caseId) {
        return jdbc.queryForObject(
                "SELECT " + column + " FROM case_authorization WHERE case_id = ?"
                        + " ORDER BY created_at DESC, authorization_id DESC LIMIT 1",
                String.class,
                caseId);
    }

    private int count(String table, String caseId) {
        return jdbc.queryForObject("SELECT COUNT(*) FROM " + table + " WHERE case_id = ?", Integer.class, caseId);
    }

    private List<String> summaries(String caseId, String kind) {
        return jdbc.queryForList(
                "SELECT detail FROM case_timeline WHERE case_id = ? AND kind = ? ORDER BY sequence",
                String.class,
                caseId,
                kind);
    }

    @Test
    @DisplayName("a person's proposal becomes a checked proposal, a new revision and an authorisation")
    void aPersonProposalBecomesExecutable() {
        String caseId = openCase();
        JsonNode response = submit(caseId, reviewer(), request("REFUND", "人工复核后确认按丢失政策全额退款"));

        assertThat(response.get("input_revision").asInt())
                .as("a person's citation set is new decision input")
                .isEqualTo(2);
        assertThat(response.get("case_version").asLong()).isEqualTo(2L);

        JsonNode caseView = view(caseId, reviewer());
        assertThat(caseView.get("case").get("status").stringValue()).isEqualTo("PENDING_REVIEW");
        JsonNode proposal = caseView.get("proposal");
        assertThat(proposal.get("origin").stringValue()).isEqualTo("HUMAN");
        assertThat(proposal.get("authored_by").stringValue()).isEqualTo("demo-reviewer");
        assertThat(proposal.get("authored_role").stringValue()).isEqualTo("REVIEWER");
        assertThat(proposal.get("summary").stringValue())
                .as("the author's reason is the proposal's summary; there is no second free-text member")
                .isEqualTo("人工复核后确认按丢失政策全额退款");
        assertThat(proposal.get("recommended_action").stringValue()).isEqualTo("REFUND");
        assertThat(proposal.get("status").stringValue()).isEqualTo("VALIDATED");
        assertThat(proposal.get("recomputed_amount_minor").asLong())
                .as("the amount is this service's recomputation, and the request had no amount to send")
                .isEqualTo(AMOUNT);
        for (String runShaped : List.of("run_id", "case_type", "reason_codes", "suggested_amount_minor")) {
            assertThat(proposal.has(runShaped))
                    .as(runShaped + " belongs to a run's proposal, and no run wrote this one")
                    .isFalse();
        }

        JsonNode authorisation = caseView.get("authorization");
        assertThat(authorisation.get("status").stringValue()).isEqualTo("PENDING_REVIEW");
        assertThat(authorisation.get("input_revision").asInt())
                .as("the authorisation is fixed to the revision the person wrote for")
                .isEqualTo(2);
        assertThat(authorisation.get("action").stringValue()).isEqualTo("REFUND");

        assertThat(column("case_proposal", "run_id", caseId)).isNull();
        assertThat(column("case_proposal", "origin", caseId)).isEqualTo("HUMAN");
        assertThat(column("case_proposal", "authored_by", caseId)).isEqualTo("demo-reviewer");
        assertThat(count("case_timeline", caseId)).isGreaterThanOrEqualTo(3);

        List<String> proposalRows = summaries(caseId, "PROPOSAL_READY");
        assertThat(proposalRows).hasSize(1);
        assertThat(proposalRows.get(0))
                .contains("HUMAN")
                .contains("demo-reviewer")
                .contains("2");
        assertThat(summaries(caseId, "APPROVAL_REQUIRED")).hasSize(1);
    }

    @Test
    @DisplayName("the reviewer then approves the authorisation the person's proposal produced")
    void theApprovalFollowsTheNewAuthorisation() {
        String caseId = openCase();
        submit(caseId, reviewer(), request("REFUND", "人工复核后确认按丢失政策全额退款"));
        String authorizationId = view(caseId, reviewer())
                .get("authorization")
                .get("authorization_id")
                .stringValue();

        JsonNode decided = decide(caseId, authorizationId, 1, "APPROVE");

        assertThat(decided.get("status").stringValue()).isEqualTo("APPROVED");
        assertThat(view(caseId, reviewer()).get("case").get("status").stringValue())
                .as("approving is not paying: consumption is C04/C05")
                .isEqualTo("AUTHORIZED");
        assertThat(newestAuthorization("decided_by", caseId)).isEqualTo("demo-reviewer");
    }

    @Test
    @DisplayName("a second proposal retires the approval the first one earned")
    void aNewProposalRetiresTheAuthorisationItReplaces() {
        String caseId = openCase();
        submit(caseId, reviewer(), request("REFUND", "第一次人工方案"));
        String first = view(caseId, reviewer())
                .get("authorization")
                .get("authorization_id")
                .stringValue();
        decide(caseId, first, 1, "APPROVE");

        JsonNode second = submit(caseId, reviewer(), request("REFUND", "第二次人工方案，补充了承运商证明"));

        assertThat(second.get("input_revision").asInt()).isEqualTo(3);
        assertThat(column("aftersale_case", "status", caseId))
                .as("an approval over input that has moved is not kept")
                .isEqualTo("PENDING_REVIEW");
        assertThat(newestAuthorization("status", caseId))
                .as("the case view shows the newest authorisation, which is the new one")
                .isEqualTo("PENDING_REVIEW");
        assertThat(jdbc.queryForObject(
                        "SELECT status FROM case_authorization WHERE authorization_id = ?", String.class, first))
                .as("the approval from the previous revision is withdrawn, not silently kept")
                .isEqualTo("REVOKED");
        assertThat(jdbc.queryForObject(
                        "SELECT decision_reason FROM case_authorization WHERE authorization_id = ?",
                        String.class,
                        first))
                .contains("superseded by proposal")
                .contains("input revision 3");
        assertThat(jdbc.queryForList(
                        "SELECT detail FROM case_timeline WHERE case_id = ? AND kind = 'AUTHORIZATION_DECIDED'",
                        String.class,
                        caseId))
                .as("the withdrawal is now this row's reason, so the approval it replaced stays readable"
                        + " in the trajectory — rows carry the current state, the trajectory carries history")
                .anySatisfy(detail -> assertThat(detail).contains(first).contains("APPROVE"));
        assertThat(jdbc.queryForObject(
                        "SELECT COUNT(*) FROM case_authorization WHERE authorization_id = ?"
                                + " AND decided_by = 'demo-reviewer' AND decided_at IS NOT NULL",
                        Integer.class,
                        first))
                .as("the withdrawal did not pretend a second person decided it")
                .isEqualTo(1);
        assertThat(jdbc.queryForObject(
                        "SELECT COUNT(*) FROM case_authorization WHERE case_id = ? AND status IN"
                                + " ('PENDING_REVIEW','APPROVED')",
                        Integer.class,
                        caseId))
                .as("the live marker's unique key allows exactly one live authorisation")
                .isEqualTo(1);

        // The withdrawn one can no longer be decided, however well-formed the request looks.
        ObjectNode body = MAPPER.createObjectNode();
        body.put("authorization_id", first);
        body.put("authorization_version", 1);
        body.put("decision", "APPROVE");
        body.put("reason", "想再批一次");
        long caseVersion = view(caseId, reviewer()).get("case").get("version").asLong();
        assertThat(rest.post()
                        .uri("/api/v1/cases/" + caseId + "/reviews")
                        .header("Authorization", "Bearer " + reviewer())
                        .header("If-Match", "\"" + caseVersion + "\"")
                        .contentType(MediaType.APPLICATION_JSON)
                        .body(body.toString())
                        .headers(h -> addCollaborationHeader(h, caseId))
                        .exchange()
                        .returnResult(String.class)
                        .getStatus()
                        .value())
                .isEqualTo(409);
    }

    @Test
    @DisplayName("a refused submission is answered and writes nothing at all")
    void aRefusedSubmissionChangesNothing() {
        String caseId = openCase();
        long versionBefore =
                jdbc.queryForObject("SELECT version FROM aftersale_case WHERE case_id = ?", Long.class, caseId);

        ObjectNode unpinned = request("REFUND", "引用了一个没有钉在本工单上的版本");
        unpinned.putArray("policy_refs").removeAll();
        ObjectNode unpinnedCitation = MAPPER.createObjectNode();
        unpinnedCitation.put("bundle_id", "policy-logistics-2026.08");
        unpinnedCitation.put("version", "2026.08");
        unpinnedCitation.put("rule_id", "R-LOST-001");
        unpinnedCitation.put("chunk_id", "c-01");
        unpinnedCitation.put("content_hash", "2".repeat(64));
        ((ArrayNode) unpinned.get("policy_refs")).add(unpinnedCitation);
        assertThat(submitStatus(caseId, reviewer(), unpinned))
                .as("a citation this service cannot verify is the submission's own fault")
                .isEqualTo(422);

        ObjectNode wrongAction = request("RESHIP", "补发而不是退款");
        assertThat(submitStatus(caseId, reviewer(), wrongAction)).isEqualTo(422);

        ObjectNode noEvidence = request("REFUND", "没有材料引用");
        noEvidence.putArray("evidence_refs").removeAll();
        assertThat(submitStatus(caseId, reviewer(), noEvidence)).isEqualTo(422);

        ObjectNode urlRef = request("REFUND", "材料引用是一个URL");
        ((ObjectNode) urlRef.get("evidence_refs").get(0)).put("source_ref", "https://example.test/whatever");
        assertThat(submitStatus(caseId, reviewer(), urlRef))
                .as("a reference is a mapping to look up, not something to fetch")
                .isEqualTo(422);

        // C05.4d: the contract marks all four members of an evidence reference required
        // (contracts/core/openapi-case.yaml:1465), and source_version and content_hash are precisely what a later
        // verification compares. A citation missing them can never be checked — and it used to be accepted and
        // written into the stored proposal with the member absent (ManualProposalService:158).
        ObjectNode noHash = request("REFUND", "材料引用没有 content_hash");
        ((ObjectNode) noHash.get("evidence_refs").get(0)).remove("content_hash");
        assertThat(submitStatus(caseId, reviewer(), noHash))
                .as("a reference without its hash is a reference nobody can ever check")
                .isEqualTo(422);

        ObjectNode notAHash = request("REFUND", "材料引用的 content_hash 不是 sha256");
        ((ObjectNode) notAHash.get("evidence_refs").get(0)).put("content_hash", "not-a-hash");
        assertThat(submitStatus(caseId, reviewer(), notAHash))
                .as("the contract says Sha256Hex, so a free-form string is not a hash")
                .isEqualTo(422);

        ObjectNode noVersion = request("REFUND", "材料引用没有 source_version");
        ((ObjectNode) noVersion.get("evidence_refs").get(0)).remove("source_version");
        assertThat(submitStatus(caseId, reviewer(), noVersion))
                .as("the version is the other half of what verification compares")
                .isEqualTo(422);

        ObjectNode blankReason = request("REFUND", "   ");
        assertThat(submitStatus(caseId, reviewer(), blankReason)).isEqualTo(422);

        assertThat(jdbc.queryForObject("SELECT version FROM aftersale_case WHERE case_id = ?", Long.class, caseId))
                .isEqualTo(versionBefore);
        assertThat(column("aftersale_case", "input_revision", caseId)).isEqualTo("1");
        assertThat(column("aftersale_case", "status", caseId)).isEqualTo("QUEUED");
        assertThat(count("case_proposal", caseId)).isZero();
        assertThat(count("case_authorization", caseId)).isZero();
    }

    @Test
    @DisplayName("a line with nothing left to refund is a conflict, not a fault in the submission")
    void anEmptyLineIsAConflict() {
        String caseId = openCase();
        commerce.refundedAmount = AMOUNT;

        assertThat(submitStatus(caseId, reviewer(), request("REFUND", "行已经退完了")))
                .as("the submission is well-formed; the world is what refuses")
                .isEqualTo(409);
        assertThat(column("aftersale_case", "input_revision", caseId)).isEqualTo("1");
        assertThat(count("case_proposal", caseId)).isZero();
        assertThat(count("case_authorization", caseId)).isZero();
    }

    @Test
    @DisplayName("the manual path is staff-only, merchant-scoped and refuses a case it cannot see")
    void theManualPathIsStaffOnly() {
        String caseId = openCase();

        assertThat(submitStatus(caseId, customer(), request("REFUND", "我自己提一个方案")))
                .as("the person who asked for the money does not write the merchant's proposal")
                .isEqualTo(403);
        String otherMerchant = new JwtCodec(secret, Duration.ofHours(1))
                .issue(new AuthenticatedPrincipal("demo-reviewer-m2", "M-1002", Role.REVIEWER, null), Instant.now());
        assertThat(submitStatus(caseId, otherMerchant, request("REFUND", "别人的工单")))
                .isEqualTo(404);
        assertThat(submitStatus(UUID.randomUUID().toString(), reviewer(), request("REFUND", "不存在的工单")))
                .isEqualTo(404);
        assertThat(count("case_proposal", caseId)).isZero();
    }

    @Test
    @DisplayName("a case whose input is frozen cannot start a revision, however good the proposal is")
    void aFrozenCaseCannotStartARevision() {
        String caseId = openCase();
        rest.post()
                .uri("/api/v1/cases/" + caseId + "/cancel")
                .header("Authorization", "Bearer " + customer())
                .contentType(MediaType.APPLICATION_JSON)
                .body("{\"reason\":\"客户撤回诉求\"}")
                .headers(h -> addReviewHeaders(h, caseId))
                .exchange()
                .expectStatus()
                .isOk();

        assertThat(submitStatus(caseId, reviewer(), request("REFUND", "工单已取消后再提方案")))
                .isEqualTo(409);
        assertThat(column("aftersale_case", "input_revision", caseId)).isEqualTo("1");
        assertThat(count("case_proposal", caseId)).isZero();
    }
}
