package com.resolveflow.caseservice.casefile;

import static org.assertj.core.api.Assertions.assertThat;

import com.resolveflow.caseservice.CaseDatabaseTest;
import com.resolveflow.caseservice.policy.PolicyRule;
import com.resolveflow.shared.security.AuthenticatedPrincipal;
import com.resolveflow.shared.security.JwtCodec;
import com.resolveflow.shared.security.Role;
import java.time.Duration;
import java.time.Instant;
import java.util.List;
import java.util.Map;
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
import org.springframework.http.HttpHeaders;
import org.springframework.http.MediaType;
import org.springframework.test.web.servlet.client.RestTestClient;
import tools.jackson.databind.JsonNode;
import tools.jackson.databind.ObjectMapper;
import tools.jackson.databind.node.ArrayNode;
import tools.jackson.databind.node.ObjectNode;

/**
 * New input retires the approval fixed to the old revision (C03.3c-2, docs/domain-model.md:36).
 *
 * <p>An authorisation is created against one input revision and its payload hash covers that revision's
 * citations (docs/core-contracts.md:68), so an approval can only ever be applied to the input it was fixed
 * for. Three routes write new input; a manual proposal was covered in C03.3c-1 and the two evidence routes
 * are covered here. The property under test is that the approval is <em>retired in the same transaction</em>
 * — not left alive for the approval path to refuse later, which would leave a window in which the case view
 * says "approved" about input the case no longer has.
 *
 * <p>Both conclusions are exercised on the verification route, because the temptation is to revoke only on
 * REFUTED ("the material was wrong"): what invalidated the payload is the revision moving, and a CONFIRMED
 * verification moves it just as far.
 */
@SpringBootTest(webEnvironment = SpringBootTest.WebEnvironment.RANDOM_PORT)
@AutoConfigureRestTestClient
class InputMovesRetireApprovalApiTest extends CaseDatabaseTest {

    private static final ObjectMapper MAPPER = new ObjectMapper();
    private static final String BUNDLE = "policy-logistics-2026.09";
    private static final String VERSION = "2026.09";
    private static final String MERCHANT = "M-1001";
    private static final String CUSTOMER = "C-2002";

    @TestConfiguration
    static class StubCommerceConfiguration {

        @Bean
        @Primary
        StubCommerce commerceStub(
                org.springframework.web.client.RestClient.Builder builder,
                @Value("${resolveflow.identity.jwt.secret}") String secret,
                @Value("${resolveflow.identity.jwt.ttl:PT1H}") Duration ttl) {
            return new StubCommerce(builder, new JwtCodec(secret, ttl));
        }
    }

    @Autowired
    RestTestClient rest;

    @Autowired
    StubCommerce commerce;

    @Value("${resolveflow.identity.jwt.secret}")
    String secret;

    private long lineCounter = 7900;

    @BeforeEach
    void prepare() {
        deleteAllCaseData(jdbc);
        commerce.reset();
    }

    private String reviewer() {
        return new JwtCodec(secret, Duration.ofHours(1))
                .issue(new AuthenticatedPrincipal("demo-reviewer", MERCHANT, Role.REVIEWER, null), Instant.now());
    }

    private String customer() {
        return new JwtCodec(secret, Duration.ofHours(1))
                .issue(new AuthenticatedPrincipal("demo-customer", MERCHANT, Role.CUSTOMER, CUSTOMER), Instant.now());
    }

    private String openCase() {
        String lineId = String.valueOf(++lineCounter);
        String body = rest.post()
                .uri("/api/v1/cases")
                .header(HttpHeaders.AUTHORIZATION, "Bearer " + customer())
                .header("Idempotency-Key", "retire-case-" + lineId)
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

    /** A policy citation whose hash is the one this service recomputes from its own stored bundle. */
    private ObjectNode policyCitation() {
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

    /** An approved authorisation on a fresh case: the state every test here starts from. */
    private String approvedCase() {
        String caseId = openCase();
        submitAndApprove(caseId, "人工复核后确认按丢失政策全额退款");
        assertThat(column("aftersale_case", "status", caseId))
                .as("the starting point of every test here is an approval")
                .isEqualTo("AUTHORIZED");
        return caseId;
    }

    /** A new manual proposal for the current revision, approved again, so a later route can retire it. */
    private String approvedAgain(String caseId) {
        return submitAndApprove(caseId, "客户补充材料后重新给出方案");
    }

    private String submitAndApprove(String caseId, String reason) {
        ObjectNode body = MAPPER.createObjectNode();
        body.put("action", "REFUND");
        ObjectNode evidence = body.putArray("evidence_refs").addObject();
        evidence.put("observation_id", UUID.randomUUID().toString());
        evidence.put("source_ref", "line:7900/shipment");
        evidence.put("source_version", "2");
        evidence.put("content_hash", "1".repeat(64));
        ArrayNode policies = body.putArray("policy_refs");
        policies.add(policyCitation());
        body.put("reason", reason);
        rest.post()
                .uri("/api/v1/cases/" + caseId + "/manual-proposals")
                .header(HttpHeaders.AUTHORIZATION, "Bearer " + reviewer())
                .contentType(MediaType.APPLICATION_JSON)
                .body(body.toString())
                .exchange()
                .expectStatus()
                .isOk();

        String authorizationId = authorisationOf(caseId);
        ObjectNode decision = MAPPER.createObjectNode();
        decision.put("authorization_id", authorizationId);
        decision.put("authorization_version", 1);
        decision.put("decision", "APPROVE");
        decision.put("reason", "依据与金额都核对过了，批准");
        rest.post()
                .uri("/api/v1/cases/" + caseId + "/reviews")
                .header(HttpHeaders.AUTHORIZATION, "Bearer " + reviewer())
                .header(
                        "If-Match",
                        "\"" + caseView(caseId).get("case").get("version").asLong() + "\"")
                .contentType(MediaType.APPLICATION_JSON)
                .body(decision.toString())
                .exchange()
                .expectStatus()
                .isOk();
        return authorizationId;
    }

    private JsonNode caseView(String caseId) {
        String body = rest.get()
                .uri("/api/v1/cases/" + caseId)
                .header(HttpHeaders.AUTHORIZATION, "Bearer " + reviewer())
                .exchange()
                .expectStatus()
                .isOk()
                .expectBody(String.class)
                .returnResult()
                .getResponseBody();
        return MAPPER.readTree(body);
    }

    private String authorisationOf(String caseId) {
        return caseView(caseId).get("authorization").get("authorization_id").stringValue();
    }

    private String column(String table, String column, String caseId) {
        return jdbc.queryForObject("SELECT " + column + " FROM " + table + " WHERE case_id = ?", String.class, caseId);
    }

    private String authorizationColumn(String column, String authorizationId) {
        return jdbc.queryForObject(
                "SELECT " + column + " FROM case_authorization WHERE authorization_id = ?",
                String.class,
                authorizationId);
    }

    private int liveAuthorisations(String caseId) {
        return jdbc.queryForObject(
                "SELECT COUNT(*) FROM case_authorization WHERE case_id = ? AND status IN ('PENDING_REVIEW','APPROVED')",
                Integer.class,
                caseId);
    }

    @Test
    @DisplayName("material appended after an approval retires it, and the answer names what it retired")
    void materialRetiresTheApproval() {
        String caseId = approvedCase();
        String approved = authorisationOf(caseId);

        String answer = rest.post()
                .uri("/api/v1/cases/" + caseId + "/evidence")
                .header(HttpHeaders.AUTHORIZATION, "Bearer " + customer())
                .contentType(MediaType.APPLICATION_JSON)
                .body(Map.of("text", "包裹其实昨天到了驿站", "evidence_kind", "CUSTOMER_STATEMENT"))
                .exchange()
                .expectStatus()
                .isOk()
                .expectBody(String.class)
                .returnResult()
                .getResponseBody();
        JsonNode response = MAPPER.readTree(answer);

        assertThat(response.get("revoked_authorization_id").stringValue())
                .as("the caller is told which approval its material retired")
                .isEqualTo(approved);
        assertThat(authorizationColumn("status", approved))
                .as("an approval fixed to the old revision is withdrawn, not left alive")
                .isEqualTo("REVOKED");
        assertThat(authorizationColumn("decision_reason", approved))
                .as("the reason names the act that retired it")
                .contains("new customer material")
                .contains("revision " + response.get("input_revision").asInt());
        assertThat(column("aftersale_case", "status", caseId))
                .as("the case goes back to waiting for a reviewer: approving was never paying")
                .isEqualTo("PENDING_REVIEW");
        assertThat(liveAuthorisations(caseId))
                .as("and nothing is left alive in its place, because no proposal has been made for this revision")
                .isZero();
    }

    @Test
    @DisplayName("a verification retires the approval whether it confirms or refutes the material")
    void aVerificationRetiresTheApproval() {
        for (String verdict : List.of("CONFIRMED", "REFUTED")) {
            String caseId = approvedCase();
            String approved = authorisationOf(caseId);
            String sourceId = appendStatement(caseId, "包裹在分拨中心停了七天");

            // The material append above already retired the approval, so this sub-case needs a fresh one to
            // test the verification route on its own rather than the append route twice.
            assertThat(authorizationColumn("status", approved)).isEqualTo("REVOKED");
            String second = approvedAgain(caseId);

            JsonNode response = MAPPER.readTree(rest.post()
                    .uri("/api/v1/cases/" + caseId + "/reviewed-evidence")
                    .header(HttpHeaders.AUTHORIZATION, "Bearer " + reviewer())
                    .contentType(MediaType.APPLICATION_JSON)
                    .body(Map.of(
                            "source_evidence_id", sourceId,
                            "verification_result", verdict,
                            "reason", "承运商系统复核后的结论：" + verdict))
                    .exchange()
                    .expectStatus()
                    .isOk()
                    .expectBody(String.class)
                    .returnResult()
                    .getResponseBody());

            assertThat(response.get("revoked_authorization_id").stringValue())
                    .as("a " + verdict + " verification is new input like any other, and names what it retired")
                    .isEqualTo(second);
            assertThat(authorizationColumn("status", second)).isEqualTo("REVOKED");
            assertThat(authorizationColumn("decision_reason", second)).contains("a reviewer's verification " + verdict);
        }
    }

    @Test
    @DisplayName("a case with no approval answers with no revocation rather than an invented one")
    void nothingToRetireIsAbsent() {
        String caseId = openCase();
        String sourceId = appendStatement(caseId, "包裹没有收到");

        String answer = rest.post()
                .uri("/api/v1/cases/" + caseId + "/reviewed-evidence")
                .header(HttpHeaders.AUTHORIZATION, "Bearer " + reviewer())
                .contentType(MediaType.APPLICATION_JSON)
                .body(Map.of(
                        "source_evidence_id", sourceId,
                        "verification_result", "CONFIRMED",
                        "reason", "承运商系统确认该件仍在运输中"))
                .exchange()
                .expectStatus()
                .isOk()
                .expectBody(String.class)
                .returnResult()
                .getResponseBody();

        assertThat(MAPPER.readTree(answer).has("revoked_authorization_id"))
                .as("there was nothing to retire, and the answer says so by saying nothing")
                .isFalse();
        assertThat(jdbc.queryForObject(
                        "SELECT COUNT(*) FROM case_authorization WHERE case_id = ?", Integer.class, caseId))
                .isZero();
    }

    /** The customer's own material, returned as the id a verification has to cite. */
    private String appendStatement(String caseId, String text) {
        rest.post()
                .uri("/api/v1/cases/" + caseId + "/evidence")
                .header(HttpHeaders.AUTHORIZATION, "Bearer " + customer())
                .contentType(MediaType.APPLICATION_JSON)
                .body(Map.of("text", text, "evidence_kind", "CUSTOMER_STATEMENT"))
                .exchange()
                .expectStatus()
                .isOk();
        return caseView(caseId).get("evidence").get(0).get("observation_id").stringValue();
    }
}
