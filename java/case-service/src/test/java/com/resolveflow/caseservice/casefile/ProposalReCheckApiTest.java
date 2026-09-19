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
 * What Java does with a proposal before it counts as one (docs/product-spec.md:25).
 *
 * <p>The claim under test is that the amount and the citations are <b>this service's</b> conclusions: the
 * run's suggestion is kept beside the recomputed one and never used, a citation is resolved against the
 * version pinned on the case and re-hashed from the stored rule text, and a proposal that cannot be checked
 * is recorded as refused with the reason a reviewer has to act on.
 *
 * <p>The two kinds of refusal are deliberately different and both are asserted: a message that is not a
 * proposal at all is a 422 (the producer sent something meaningless), while a proposal that was checked and
 * refused is stored as REJECTED and shown in the case view.
 */
@SpringBootTest(webEnvironment = SpringBootTest.WebEnvironment.RANDOM_PORT)
@AutoConfigureRestTestClient
class ProposalReCheckApiTest extends CaseDatabaseTest {

    private static final ObjectMapper MAPPER = new ObjectMapper();
    private static final String RUN = "b7b7b7b7-4444-4555-8666-bbbbbbbbbbbb";
    private static final String BUNDLE = "policy-logistics-2026.09";
    private static final String VERSION = "2026.09";
    private static final Instant PAID_IN_SEPTEMBER = Instant.parse("2026-09-10T08:15:00Z");

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

    private long lineCounter = 7500;

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

    private String serviceToken() {
        return new JwtCodec(secret, Duration.ofHours(1)).issueServiceToken("agent-service", Instant.now());
    }

    private String userToken() {
        return new JwtCodec(secret, Duration.ofHours(1))
                .issue(new AuthenticatedPrincipal("demo-customer", "M-1001", Role.CUSTOMER, "C-2002"), Instant.now());
    }

    /** Opens a case on the real fixture policy set, so the case has a pinned version to cite. */
    private String openCase() {
        String lineId = String.valueOf(++lineCounter);
        String body = rest.post()
                .uri("/api/v1/cases")
                .header("Authorization", "Bearer " + userToken())
                .header("Idempotency-Key", "proposal-case-" + lineId)
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

    /**
     * A citation built the way a run builds one: from what the policy route serves.
     *
     * <p>{@link PolicyRule#from} is the same construction the route uses, so a test can produce the citation a
     * run would copy; whether the two agree across languages is pinned separately, against the frozen corpus
     * (PolicyApiTest and agent/tests/unit/test_contracts_fixtures.py).
     */
    private ObjectNode citationFor(String bundleId, String ruleId) {
        return jdbc.query(
                "SELECT position, rule_id, title, text FROM policy_rule WHERE bundle_id = ? AND rule_id = ?",
                resultSet -> {
                    assertThat(resultSet.next())
                            .as("the fixture bundle has rule " + ruleId)
                            .isTrue();
                    PolicyRule rule = PolicyRule.from(
                            bundleId,
                            resultSet.getInt("position"),
                            resultSet.getString("rule_id"),
                            resultSet.getString("title"),
                            resultSet.getString("text"));
                    ObjectNode citation = MAPPER.createObjectNode();
                    citation.put("bundle_id", bundleId);
                    citation.put("version", VERSION);
                    citation.put("rule_id", ruleId);
                    citation.put("chunk_id", rule.chunkId());
                    citation.put("content_hash", rule.contentHash());
                    return citation;
                },
                bundleId,
                ruleId);
    }

    /** A REFUND proposal with one valid citation and a suggestion. */
    private ObjectNode refundProposal(String caseId, int revision, Long suggested) {
        ObjectNode payload = proposal(caseId, revision, "REFUND");
        payload.put("summary", "承运商判定丢失，按 2026.09 政策全额退款");
        if (suggested != null) {
            payload.put("suggested_amount_minor", suggested);
        }
        payload.putArray("policy_refs").add(citationFor(BUNDLE, "R-LOST-001"));
        return payload;
    }

    private ObjectNode proposal(String caseId, int revision, String action) {
        ObjectNode payload = MAPPER.createObjectNode();
        payload.put("schema_version", 2);
        payload.put("proposal_id", java.util.UUID.randomUUID().toString());
        payload.put("run_id", RUN);
        payload.put("case_id", caseId);
        payload.put("input_revision", revision);
        payload.put("case_type", "LOGISTICS");
        payload.put("recommended_action", action);
        payload.put("summary", "调查结论");
        payload.putArray("reason_codes").add("CARRIER_LOST");
        return payload;
    }

    private ObjectNode envelope(String callbackId, int revision, ObjectNode payload) {
        ObjectNode body = MAPPER.createObjectNode();
        body.put("callback_id", callbackId);
        body.put("run_id", RUN);
        body.put("input_revision", revision);
        body.put("kind", "PROPOSAL");
        body.set("payload", payload);
        body.put("traceparent", "00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01");
        return body;
    }

    private JsonNode deliver(String callbackId, String caseId, ObjectNode payload) {
        String response = rest.post()
                .uri("/internal/v1/cases/" + caseId + "/agent-callbacks")
                .header("Authorization", "Bearer " + serviceToken())
                .contentType(org.springframework.http.MediaType.APPLICATION_JSON)
                .body(envelope(callbackId, revision(caseId), payload).toString())
                .exchange()
                .expectStatus()
                .isOk()
                .expectBody(String.class)
                .returnResult()
                .getResponseBody();
        return MAPPER.readTree(response);
    }

    private String deliverExpecting(String callbackId, String caseId, ObjectNode payload, int status) {
        return rest.post()
                .uri("/internal/v1/cases/" + caseId + "/agent-callbacks")
                .header("Authorization", "Bearer " + serviceToken())
                .contentType(org.springframework.http.MediaType.APPLICATION_JSON)
                .body(envelope(callbackId, revision(caseId), payload).toString())
                .exchange()
                .expectStatus()
                .isEqualTo(status)
                .expectBody(String.class)
                .returnResult()
                .getResponseBody();
    }

    /** The case view the user reads, proposal member included. */
    private JsonNode view(String caseId) {
        String body = rest.get()
                .uri("/api/v1/cases/" + caseId)
                .header("Authorization", "Bearer " + userToken())
                .exchange()
                .expectStatus()
                .isOk()
                .expectBody(String.class)
                .returnResult()
                .getResponseBody();
        return MAPPER.readTree(body);
    }

    private String status(String caseId) {
        return jdbc.queryForObject("SELECT status FROM aftersale_case WHERE case_id = ?", String.class, caseId);
    }

    private int revision(String caseId) {
        return jdbc.queryForObject(
                "SELECT input_revision FROM aftersale_case WHERE case_id = ?", Integer.class, caseId);
    }

    private String storedStatus(String caseId) {
        return jdbc.queryForObject("SELECT status FROM case_proposal WHERE case_id = ?", String.class, caseId);
    }

    private String storedReason(String caseId) {
        return jdbc.queryForObject("SELECT refusal_reason FROM case_proposal WHERE case_id = ?", String.class, caseId);
    }

    @Test
    @DisplayName("a checked refund is stored VALIDATED with the amount Java recomputed, and a person decides")
    void aCheckedRefundIsValidated() {
        String caseId = openCase();

        JsonNode response = deliver("proposal-ok", caseId, refundProposal(caseId, 1, 2000L));

        assertThat(response.get("disposition").stringValue()).isEqualTo("ACCEPTED");
        assertThat(status(caseId))
                .as("the handoff: the run is done, a person owns the case")
                .isEqualTo("PENDING_REVIEW");
        assertThat(storedStatus(caseId))
                .as("refusal reason: " + storedReason(caseId))
                .isEqualTo("VALIDATED");

        // The line is paid 2599 with nothing refunded or reserved, so that is the amount - not the run's 2000.
        JsonNode proposal = view(caseId).get("proposal");
        assertThat(proposal.get("status").stringValue()).isEqualTo("VALIDATED");
        assertThat(proposal.get("recomputed_amount_minor").asLong())
                .as("Java owns the amount: the recomputed one is what the view shows")
                .isEqualTo(2599L);
        assertThat(proposal.get("suggested_amount_minor").asLong())
                .as("the suggestion stays visible beside it, because a disagreement is worth reading")
                .isEqualTo(2000L);
        assertThat(proposal.get("policy_refs").get(0).get("rule_id").stringValue())
                .isEqualTo("R-LOST-001");
        assertThat(proposal.has("refusal_reason")).isFalse();
        assertThat(proposal.get("reason_codes").get(0).stringValue()).isEqualTo("CARRIER_LOST");
    }

    @Test
    @DisplayName("a case with no pinned version cannot have its citations checked, and that is a refusal")
    void aCaseWithNoPinnedVersionCannotBeChecked() {
        String caseId = openCase();
        // A case that was opened while no policy version covered its payment has nothing pinned; the
        // citations a run would make then have no version to be resolved against (C03.1b).
        jdbc.update("DELETE FROM case_policy_bundle WHERE case_id = ?", caseId);
        jdbc.update("DELETE FROM case_policy_manifest WHERE case_id = ?", caseId);

        deliver("proposal-unpinned", caseId, refundProposal(caseId, 1, null));

        assertThat(storedStatus(caseId)).isEqualTo("REJECTED");
        assertThat(storedReason(caseId)).contains("no pinned policy version");
    }

    @Test
    @DisplayName("a suggestion larger than the line can refund is refused, and the reason names both numbers")
    void aSuggestionBeyondTheLineIsRefused() {
        String caseId = openCase();

        deliver("proposal-greedy", caseId, refundProposal(caseId, 1, 2600L));

        assertThat(storedStatus(caseId)).isEqualTo("REJECTED");
        assertThat(storedReason(caseId)).contains("2600").contains("2599");
    }

    @Test
    @DisplayName("a citation whose hash is not the stored rule's is refused with both hashes")
    void aWrongHashIsRefused() {
        String caseId = openCase();
        ObjectNode payload = refundProposal(caseId, 1, null);
        ((ObjectNode) payload.get("policy_refs").get(0)).put("content_hash", "0".repeat(64));

        deliver("proposal-badhash", caseId, payload);

        assertThat(storedStatus(caseId)).isEqualTo("REJECTED");
        assertThat(storedReason(caseId)).contains("0".repeat(64)).contains("hashes to");
        assertThat(view(caseId).get("proposal").get("status").stringValue()).isEqualTo("REJECTED");
    }

    @Test
    @DisplayName("citing a version this case is not pinned to is refused, even though the bundle exists")
    void aCitationOfAnotherVersionIsRefused() {
        String caseId = openCase();
        ObjectNode payload = refundProposal(caseId, 1, null);
        ObjectNode citation = (ObjectNode) payload.get("policy_refs").get(0);
        citation.put("bundle_id", "policy-logistics-2026.08");
        citation.put("version", "2026.08");

        deliver("proposal-oldpolicy", caseId, payload);

        assertThat(storedStatus(caseId)).isEqualTo("REJECTED");
        assertThat(storedReason(caseId))
                .as("pinning is the point: a September payment is not decided under the August rules")
                .contains("policy-logistics-2026.08")
                .contains("pinned")
                .contains(BUNDLE);
    }

    @Test
    @DisplayName("a rule that is not in the cited bundle is refused")
    void anUnknownRuleIsRefused() {
        String caseId = openCase();
        ObjectNode payload = refundProposal(caseId, 1, null);
        ObjectNode citation = (ObjectNode) payload.get("policy_refs").get(0);
        citation.put("rule_id", "R-NOPE-001");

        deliver("proposal-unknownrule", caseId, payload);

        assertThat(storedStatus(caseId)).isEqualTo("REJECTED");
        assertThat(storedReason(caseId)).contains("R-NOPE-001").contains("is not in");
    }

    @Test
    @DisplayName("a refund proposal with no citation at all is refused: there would be nothing to check")
    void aRefundWithoutACitationIsRefused() {
        String caseId = openCase();
        ObjectNode payload = proposal(caseId, 1, "REFUND");
        payload.put("summary", "按经验应当退款");

        deliver("proposal-nocitation", caseId, payload);

        assertThat(storedStatus(caseId)).isEqualTo("REJECTED");
        assertThat(storedReason(caseId)).contains("cite the policy");
    }

    @Test
    @DisplayName("a line the order's ledger has already paid out is refused rather than refunded twice")
    void aLineWithNothingLeftIsRefused() {
        String caseId = openCase();
        commerce.refundedAmount = 2599;

        deliver("proposal-exhausted", caseId, refundProposal(caseId, 1, null));

        assertThat(storedStatus(caseId)).isEqualTo("REJECTED");
        assertThat(storedReason(caseId)).contains("nothing left to refund");
    }

    @Test
    @DisplayName("a line that belongs to someone else is refused: the context is where ownership is confirmed")
    void aLineThatIsNotThisCasesLineIsRefused() {
        String caseId = openCase();
        commerce.lineOwnerMismatch = true;

        deliver("proposal-foreignline", caseId, refundProposal(caseId, 1, null));

        assertThat(storedStatus(caseId)).isEqualTo("REJECTED");
        assertThat(storedReason(caseId)).contains("another merchant or customer");
    }

    @Test
    @DisplayName("a line Commerce no longer has is refused, not retried: a refund needs a record to pay from")
    void aMissingLineIsRefused() {
        String caseId = openCase();
        commerce.lineVisible = false;

        deliver("proposal-noline", caseId, refundProposal(caseId, 1, null));

        assertThat(storedStatus(caseId)).isEqualTo("REJECTED");
        assertThat(storedReason(caseId)).contains("no longer has line");
    }

    @Test
    @DisplayName("an action that does not move money is validated without inventing an amount")
    void aNonRefundActionNeedsNoAmount() {
        String caseId = openCase();
        ObjectNode payload = proposal(caseId, 1, "MANUAL_REVIEW");
        payload.put("summary", "签收记录与客户主张冲突，需人工核验");

        deliver("proposal-manual", caseId, payload);

        assertThat(storedStatus(caseId))
                .as("refusal reason: " + storedReason(caseId))
                .isEqualTo("VALIDATED");
        JsonNode proposal = view(caseId).get("proposal");
        assertThat(proposal.get("status").stringValue()).isEqualTo("VALIDATED");
        assertThat(proposal.has("recomputed_amount_minor"))
                .as("no amount is recomputed for an action that does not move money")
                .isFalse();
        assertThat(status(caseId)).isEqualTo("PENDING_REVIEW");
    }

    @Test
    @DisplayName("a message that is not a proposal is a 422, and it leaves nothing behind")
    void protocolErrorsAreRefusedAndChangeNothing() {
        String caseId = openCase();

        ObjectNode wrongCase = refundProposal(caseId, 1, null);
        wrongCase.put("case_id", java.util.UUID.randomUUID().toString());
        assertThat(deliverExpecting("p1", caseId, wrongCase, 422)).contains("case_id");

        ObjectNode wrongRevision = refundProposal(caseId, 1, null);
        wrongRevision.put("input_revision", 7);
        assertThat(deliverExpecting("p2", caseId, wrongRevision, 422)).contains("input_revision");

        ObjectNode unknownAction = refundProposal(caseId, 1, null);
        unknownAction.put("recommended_action", "RESHIP");
        assertThat(deliverExpecting("p3", caseId, unknownAction, 422)).contains("RESHIP");

        ObjectNode oldSchema = refundProposal(caseId, 1, null);
        oldSchema.put("schema_version", 1);
        assertThat(deliverExpecting("p4", caseId, oldSchema, 422)).contains("schema_version");

        ObjectNode amountOnManual = proposal(caseId, 1, "MANUAL_REVIEW");
        amountOnManual.put("suggested_amount_minor", 100);
        assertThat(deliverExpecting("p5", caseId, amountOnManual, 422)).contains("REFUND");

        ObjectNode urlRef = refundProposal(caseId, 1, null);
        ObjectNode evidence = urlRef.putArray("evidence_refs").addObject();
        evidence.put("observation_id", "o-1");
        evidence.put("source_ref", "https://example.com/tracking");
        evidence.put("source_version", "3");
        evidence.put("content_hash", "a".repeat(64));
        assertThat(deliverExpecting("p6", caseId, urlRef, 422)).contains("source_ref");

        assertThat(jdbc.queryForObject("SELECT COUNT(*) FROM case_proposal", Integer.class))
                .as("a refused message is not a stored proposal")
                .isZero();
        assertThat(status(caseId)).as("and the case has not moved").isEqualTo("QUEUED");
    }

    @Test
    @DisplayName("a revision that already proposed is stale for a second proposal, and no second row appears")
    void aSecondProposalForTheSameRevisionIsStale() {
        String caseId = openCase();
        deliver("proposal-first", caseId, refundProposal(caseId, 1, null));

        JsonNode second = deliver("proposal-second", caseId, refundProposal(caseId, 1, null));

        assertThat(second.get("disposition").stringValue())
                .as("a person already owns the case after the first proposal")
                .isEqualTo("STALE");
        assertThat(jdbc.queryForObject("SELECT COUNT(*) FROM case_proposal", Integer.class))
                .isEqualTo(1);
    }

    @Test
    @DisplayName("a proposal the case has moved past is shown as STALE, derived rather than stored")
    void aProposalFromAnOlderRevisionIsShownStale() {
        String caseId = openCase();
        deliver("proposal-before-evidence", caseId, refundProposal(caseId, 1, null));
        assertThat(view(caseId).get("proposal").get("status").stringValue()).isEqualTo("VALIDATED");

        // The customer supplies more material, which moves the revision the proposal belonged to.
        rest.post()
                .uri("/api/v1/cases/" + caseId + "/evidence")
                .header("Authorization", "Bearer " + userToken())
                .contentType(org.springframework.http.MediaType.APPLICATION_JSON)
                .body("{\"text\":\"运单号 SF123456789\",\"evidence_kind\":\"CUSTOMER_STATEMENT\"}")
                .exchange()
                .expectStatus()
                .isOk();
        assertThat(revision(caseId)).isEqualTo(2);

        JsonNode proposal = view(caseId).get("proposal");
        assertThat(proposal.get("status").stringValue())
                .as("the stored row still says VALIDATED; the read says it is no longer about this revision")
                .isEqualTo("STALE");
        assertThat(storedStatus(caseId)).isEqualTo("VALIDATED");
        assertThat(proposal.get("input_revision").asInt()).isEqualTo(1);
    }

    @Test
    @DisplayName("the trajectory says whether the proposal could be checked, not merely that it arrived")
    void theTrajectorySaysWhatHappenedToTheProposal() {
        String caseId = openCase();
        deliver("proposal-trajectory", caseId, refundProposal(caseId, 1, 2000L));

        java.util.List<String> sentences = new java.util.ArrayList<>();
        view(caseId)
                .get("timeline")
                .forEach(event -> sentences.add(event.get("summary").stringValue()));
        assertThat(sentences)
                .as("the reader sees the amount Java recomputed, not the run's suggestion")
                .anyMatch(sentence -> sentence.contains("2599"))
                .anyMatch(sentence -> sentence.contains("等待人工确认"));

        String refusedCase = openCase();
        ObjectNode bad = refundProposal(refusedCase, 1, null);
        ((ObjectNode) bad.get("policy_refs").get(0)).put("content_hash", "1".repeat(64));
        deliver("proposal-trajectory-refused", refusedCase, bad);

        java.util.List<String> refused = new java.util.ArrayList<>();
        view(refusedCase)
                .get("timeline")
                .forEach(event -> refused.add(event.get("summary").stringValue()));
        assertThat(refused)
                .as("a refusal quotes the check that refused it, because that is what the reviewer acts on")
                .anyMatch(sentence -> sentence.contains("未通过核对") && sentence.contains("hashes to"));
    }
}
