package com.resolveflow.caseservice.casefile;

import static org.assertj.core.api.Assertions.assertThat;

import com.resolveflow.caseservice.CaseDatabaseTest;
import com.resolveflow.caseservice.policy.PolicyImportService;
import com.resolveflow.caseservice.policy.PolicyRule;
import com.resolveflow.shared.contract.CanonicalJson;
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
 * The authorisation a human decides on, created with the proposal that earned it (C03.3a).
 *
 * <p>Three claims are under test, and each is a thing that would be easy to fake:
 *
 * <ul>
 *   <li><b>The payload is fixed at creation.</b> The operation id is drawn before anyone decides and the
 *       hash covers the twelve command fields, so a retry reuses one operation instead of inventing a second
 *       payment. The test recomputes the hash from the same facts the case view exposes and the line
 *       Commerce reports — a stored hash that no reader could re-derive would be a claim, not a check.
 *   <li><b>Only something executable gets authorised.</b> A refused proposal has nothing to approve, and a
 *       validated recommendation that moves no money has nothing this service could execute; both leave the
 *       table empty rather than putting an undecidable row in front of a reviewer.
 *   <li><b>The authorisation keeps its own revision.</b> Material arriving between creation and approval
 *       moves the case on, and the view has to be able to say that the authorisation describes the earlier
 *       input — which is exactly what the approval guard has to compare (C03.3b).
 * </ul>
 */
@SpringBootTest(webEnvironment = SpringBootTest.WebEnvironment.RANDOM_PORT)
@AutoConfigureRestTestClient
class AuthorizationApiTest extends CaseDatabaseTest {

    private static final ObjectMapper MAPPER = new ObjectMapper();
    private static final String RUN = "c8c8c8c8-5555-4666-8777-cccccccccccc";
    private static final String BUNDLE = "policy-logistics-2026.09";
    private static final String VERSION = "2026.09";
    private static final String MERCHANT = "M-1001";
    /** What the stub line says: two units of CNY 2599, nothing refunded or reserved. */
    private static final int QUANTITY = 2;

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
    PolicyImportService policies;

    @Value("${resolveflow.identity.jwt.secret}")
    String secret;

    private long lineCounter = 7600;

    @BeforeEach
    void prepare() {
        jdbc.execute("DELETE FROM case_policy_bundle");
        jdbc.execute("DELETE FROM case_policy_manifest");
        jdbc.execute("DELETE FROM policy_rule");
        jdbc.execute("DELETE FROM policy_bundle");
        policies.importDirectory(fixtureDirectory());
        deleteAllCaseData(jdbc);
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
                .issue(new AuthenticatedPrincipal("demo-customer", MERCHANT, Role.CUSTOMER, "C-2002"), Instant.now());
    }

    private String openCase() {
        String lineId = String.valueOf(++lineCounter);
        String body = rest.post()
                .uri("/api/v1/cases")
                .header("Authorization", "Bearer " + userToken())
                .header("Idempotency-Key", "authorization-case-" + lineId)
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
                    ObjectNode citation = MAPPER.createObjectNode();
                    citation.put("bundle_id", BUNDLE);
                    citation.put("version", VERSION);
                    citation.put("rule_id", "R-LOST-001");
                    citation.put("chunk_id", rule.chunkId());
                    citation.put("content_hash", rule.contentHash());
                    return citation;
                },
                BUNDLE,
                "R-LOST-001");
    }

    private ObjectNode refundProposal(String caseId, int revision, String proposalId) {
        ObjectNode payload = proposal(caseId, revision, proposalId, "REFUND");
        payload.put("summary", "承运商判定丢失，按 2026.09 政策全额退款");
        payload.put("suggested_amount_minor", 2000);
        payload.putArray("policy_refs").add(citation());
        return payload;
    }

    private ObjectNode proposal(String caseId, int revision, String proposalId, String action) {
        ObjectNode payload = MAPPER.createObjectNode();
        payload.put("schema_version", 2);
        payload.put("proposal_id", proposalId);
        payload.put("run_id", RUN);
        payload.put("case_id", caseId);
        payload.put("input_revision", revision);
        payload.put("case_type", "LOGISTICS");
        payload.put("recommended_action", action);
        payload.put("summary", "调查结论");
        payload.putArray("reason_codes").add("CARRIER_LOST");
        return payload;
    }

    private JsonNode deliver(String callbackId, String caseId, int revision, ObjectNode payload) {
        ObjectNode body = MAPPER.createObjectNode();
        body.put("callback_id", callbackId);
        body.put("run_id", RUN);
        body.put("input_revision", revision);
        body.put("kind", "PROPOSAL");
        body.set("payload", payload);
        body.put("traceparent", "00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01");
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

    private void appendMaterial(String caseId) {
        rest.post()
                .uri("/api/v1/cases/" + caseId + "/evidence")
                .header("Authorization", "Bearer " + userToken())
                .contentType(org.springframework.http.MediaType.APPLICATION_JSON)
                .body("{\"text\":\"运单号 SF123456789\",\"evidence_kind\":\"CUSTOMER_STATEMENT\"}")
                .exchange()
                .expectStatus()
                .isOk();
    }

    private String lineId(String caseId) {
        return jdbc.queryForObject("SELECT line_id FROM aftersale_case WHERE case_id = ?", String.class, caseId);
    }

    private String authorizationColumn(String caseId, String column) {
        return jdbc.queryForObject(
                "SELECT " + column + " FROM case_authorization WHERE case_id = ?", String.class, caseId);
    }

    @Test
    @DisplayName("a checked refund fixes its payload, and the hash covers the fields it claims to cover")
    void aCheckedRefundFixesItsPayload() {
        String caseId = openCase();
        String proposalId = java.util.UUID.randomUUID().toString();

        deliver("auth-ok", caseId, 1, refundProposal(caseId, 1, proposalId));

        JsonNode authorisation = view(caseId).get("authorization");
        assertThat(authorisation.get("status").stringValue()).isEqualTo("PENDING_REVIEW");
        assertThat(authorisation.get("authorization_version").asLong()).isEqualTo(1L);
        assertThat(authorisation.get("action").stringValue()).isEqualTo("REFUND");
        assertThat(authorisation.get("input_revision").asInt())
                .as("the revision whose payload was fixed, which is the case's revision at creation")
                .isEqualTo(1);
        assertThat(authorisation.get("planned_operation_id").stringValue()).matches("^[0-9a-f-]{36}$");
        assertThat(authorisation.has("expires_at"))
                .as("nothing sets an expiry yet, and absent is how the view says so")
                .isFalse();

        // The hash is recomputed here from the facts the case view exposes plus what Commerce reports for the
        // line: an authorisation whose hash could not be re-derived would be announcing a payment, not fixing one.
        RefundCommand expected = new RefundCommand(
                authorisation.get("planned_operation_id").stringValue(),
                caseId,
                authorisation.get("authorization_id").stringValue(),
                1,
                lineId(caseId),
                MERCHANT,
                ExecutableAction.REFUND,
                QUANTITY,
                "CNY",
                AMOUNT,
                VERSION);
        assertThat(authorisation.get("payload_hash").stringValue())
                .isEqualTo(expected.payloadHash(MAPPER))
                .isEqualTo(CanonicalJson.payloadHash(expected.toJson(MAPPER)));

        assertThat(authorizationColumn(caseId, "proposal_id"))
                .as("the authorisation names the proposal it was derived from")
                .isEqualTo(proposalId);
        assertThat(authorizationColumn(caseId, "amount_minor")).isEqualTo(String.valueOf(AMOUNT));
        assertThat(authorizationColumn(caseId, "quantity")).isEqualTo(String.valueOf(QUANTITY));
        assertThat(authorizationColumn(caseId, "currency")).isEqualTo("CNY");
        assertThat(authorizationColumn(caseId, "policy_version"))
                .as("the version of the policy the proposal relies on, which the command carries")
                .isEqualTo(VERSION);
    }

    @Test
    @DisplayName("the operation id is drawn once, and the trajectory says that a human has to decide")
    void theTrajectorySaysAHumanHasToDecide() {
        String caseId = openCase();
        deliver(
                "auth-trajectory",
                caseId,
                1,
                refundProposal(caseId, 1, java.util.UUID.randomUUID().toString()));

        JsonNode timeline = view(caseId).get("timeline");
        boolean waiting = false;
        for (JsonNode event : timeline) {
            if ("APPROVAL_REQUIRED".equals(event.get("type").stringValue())) {
                waiting = true;
                assertThat(event.get("summary").stringValue())
                        .as("the version is the fact the decision route checks, so the reader is told it")
                        .contains("授权版本 1");
            }
        }
        assertThat(waiting)
                .as("a proposal that was validated is not the end of the human's involvement")
                .isTrue();

        String detail = jdbc.queryForObject(
                "SELECT detail FROM case_timeline WHERE case_id = ? AND kind = 'APPROVAL_REQUIRED'",
                String.class,
                caseId);
        assertThat(detail)
                .contains(authorizationColumn(caseId, "planned_operation_id"))
                .contains(authorizationColumn(caseId, "payload_hash"));
    }

    @Test
    @DisplayName("a refused proposal authorises nothing: there is no payment for a reviewer to approve")
    void aRefusedProposalAuthorisesNothing() {
        String caseId = openCase();
        ObjectNode payload =
                refundProposal(caseId, 1, java.util.UUID.randomUUID().toString());
        ((ObjectNode) payload.get("policy_refs").get(0)).put("content_hash", "0".repeat(64));

        deliver("auth-refused", caseId, 1, payload);

        JsonNode view = view(caseId);
        assertThat(view.get("proposal").get("status").stringValue()).isEqualTo("REJECTED");
        assertThat(view.has("authorization")).isFalse();
        assertThat(jdbc.queryForObject("SELECT COUNT(*) FROM case_authorization", Integer.class))
                .isZero();
    }

    @Test
    @DisplayName("a validated recommendation that moves no money authorises nothing either")
    void aNonMoneyActionAuthorisesNothing() {
        String caseId = openCase();
        ObjectNode payload = proposal(caseId, 1, java.util.UUID.randomUUID().toString(), "MANUAL_REVIEW");
        payload.put("summary", "签收记录与客户主张冲突，需人工核验");

        deliver("auth-manual", caseId, 1, payload);

        JsonNode view = view(caseId);
        assertThat(view.get("proposal").get("status").stringValue()).isEqualTo("VALIDATED");
        assertThat(view.has("authorization"))
                .as("there is no command to execute, so there is nothing to approve")
                .isFalse();
        assertThat(jdbc.queryForObject("SELECT COUNT(*) FROM case_authorization", Integer.class))
                .isZero();
    }

    @Test
    @DisplayName("material arriving later moves the case, retires the authorisation and leaves its revision alone")
    void theAuthorisationKeepsTheRevisionItFixed() {
        String caseId = openCase();
        deliver(
                "auth-then-material",
                caseId,
                1,
                refundProposal(caseId, 1, java.util.UUID.randomUUID().toString()));

        appendMaterial(caseId);

        JsonNode view = view(caseId);
        assertThat(view.get("case").get("input_revision").asInt()).isEqualTo(2);
        assertThat(view.get("authorization").get("input_revision").asInt())
                .as("an approved payload for revision 1 is not a payload for revision 2")
                .isEqualTo(1);
        // C03.3c-2: new input retires the live authorisation, in the transaction that writes the material.
        // C03.3b left it PENDING_REVIEW for the approval path to refuse later, which left a window in which
        // the case view said an approval for revision 1 was still available on revision 2.
        assertThat(view.get("authorization").get("status").stringValue())
                .as("an approval fixed to the previous revision cannot stay live over this one")
                .isEqualTo("REVOKED");
        assertThat(authorizationColumn(caseId, "decision_reason"))
                .as("the reason names the act that retired it, for the next reader")
                .contains("moved the input to revision 2");
        assertThat(view.get("proposal").get("status").stringValue()).isEqualTo("STALE");
    }

    @Test
    @DisplayName("one case cannot hold two live authorisations for the same operation id")
    void theOperationIdIsUnique() {
        String caseId = openCase();
        deliver(
                "auth-unique",
                caseId,
                1,
                refundProposal(caseId, 1, java.util.UUID.randomUUID().toString()));

        String operationId = authorizationColumn(caseId, "planned_operation_id");
        assertThat(operationId).isNotBlank();
        assertThat(jdbc.queryForObject(
                        "SELECT COUNT(*) FROM case_authorization WHERE planned_operation_id = ?",
                        Integer.class,
                        operationId))
                .as("a retry of this payment has to reuse this id, so it cannot be issued twice")
                .isEqualTo(1);
    }
}
