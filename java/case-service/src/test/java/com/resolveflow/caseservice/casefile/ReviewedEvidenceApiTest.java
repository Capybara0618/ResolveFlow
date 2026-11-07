package com.resolveflow.caseservice.casefile;

import static org.assertj.core.api.Assertions.assertThat;

import com.resolveflow.caseservice.CaseDatabaseTest;
import com.resolveflow.shared.security.AuthenticatedPrincipal;
import com.resolveflow.shared.security.JwtCodec;
import com.resolveflow.shared.security.Role;
import java.time.Instant;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
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
 * {@code POST /api/v1/cases/{case_id}/reviewed-evidence} (docs/core-contracts.md:35).
 *
 * <p>What is under test is that a human conclusion is a record rather than a rewrite: the verified record
 * keeps its text and its hash, the verification names what it is about and states what the reviewer found,
 * and both are readable through the case view — which is the only surface a reviewer can work from, and the
 * one the contract now declares as {@code EvidenceView}.
 *
 * <p>Most assertions read the case view rather than the database, because that is the round trip a reviewer
 * performs: read the material, name it, record the conclusion, read it back.
 */
@AutoConfigureRestTestClient
class ReviewedEvidenceApiTest extends CaseDatabaseTest {

    private static final ObjectMapper MAPPER = new ObjectMapper();
    private static final String LINE = "7001";

    @Autowired
    RestTestClient rest;

    @Autowired
    StubCommerce commerce;

    @Autowired
    JwtCodec jwtCodec;

    @Autowired
    JdbcTemplate jdbc;

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
        commerce.reset();
    }

    private static String token(JwtCodec codec, String user, String merchant, Role role, String customer) {
        return codec.issue(
                new AuthenticatedPrincipal(user, role == Role.CUSTOMER ? null : merchant, role, customer),
                Instant.now());
    }

    private String customer(String merchant, String buyerId) {
        return token(jwtCodec, "demo-customer", merchant, Role.CUSTOMER, buyerId);
    }

    private String reviewer(String username, String merchant) {
        return token(jwtCodec, username, merchant, Role.REVIEWER, null);
    }

    private String openCase(String merchant, String buyerId, String line) {
        String body = rest.post()
                .uri("/api/v1/cases")
                .header(HttpHeaders.AUTHORIZATION, "Bearer " + customer(merchant, buyerId))
                .header("Idempotency-Key", "reviewed-key-" + System.nanoTime())
                .contentType(MediaType.APPLICATION_JSON)
                .body(Map.of("line_id", line, "description", "包裹疑似丢失", "requested_actions", List.of("REFUND")))
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

    /** The customer's own material, appended through the contract route. */
    private String appendStatement(String caseId, String token, String text) {
        rest.post()
                .uri("/api/v1/cases/" + caseId + "/evidence")
                .header(HttpHeaders.AUTHORIZATION, "Bearer " + token)
                .contentType(MediaType.APPLICATION_JSON)
                .body(Map.of("text", text, "evidence_kind", "CUSTOMER_STATEMENT"))
                .headers(h -> addReviewHeaders(h, caseId))
                .exchange()
                .expectStatus()
                .isOk();
        return MAPPER.readTree(view(caseId, token))
                .get("evidence")
                .get(0)
                .get("observation_id")
                .stringValue();
    }

    private String view(String caseId, String token) {
        return rest.get()
                .uri("/api/v1/cases/" + caseId)
                .header(HttpHeaders.AUTHORIZATION, "Bearer " + token)
                .exchange()
                .expectStatus()
                .isOk()
                .expectBody(String.class)
                .returnResult()
                .getResponseBody();
    }

    private RestTestClient.ResponseSpec review(String caseId, String token, Map<String, Object> body) {
        RestTestClient.RequestHeadersSpec<?> request = rest.post()
                .uri("/api/v1/cases/" + caseId + "/reviewed-evidence")
                .contentType(MediaType.APPLICATION_JSON)
                .body(body);
        if (token != null) {
            request = request.header(HttpHeaders.AUTHORIZATION, "Bearer " + token);
        }
        return request.headers(h -> addReviewHeaders(h, caseId)).exchange();
    }

    private static Map<String, Object> verification(String sourceId, String result, String reason) {
        Map<String, Object> body = new HashMap<>();
        body.put("source_evidence_id", sourceId);
        body.put("verification_result", result);
        body.put("reason", reason);
        return body;
    }

    private int evidenceRows(String caseId, String sourceType) {
        return jdbc.queryForObject(
                "SELECT COUNT(*) FROM case_evidence WHERE case_id = ? AND source_type = ?",
                Integer.class,
                caseId,
                sourceType);
    }

    @Test
    @DisplayName("a verification is a new record: the verified material keeps its text and its hash")
    void aVerificationIsANewRecord() {
        String customerToken = customer("M-1001", "B-legacy-60865438438feefa1dfbc0ce3d07ba2cb1b09a80");
        String reviewerToken = reviewer("demo-reviewer", "M-1001");
        String caseId = openCase("M-1001", "B-legacy-60865438438feefa1dfbc0ce3d07ba2cb1b09a80", LINE);
        String statement = "包裹在分拨中心停了七天没有任何更新";
        String sourceId = appendStatement(caseId, customerToken, statement);

        JsonNode before = MAPPER.readTree(view(caseId, reviewerToken));
        JsonNode original = before.get("evidence").get(0);
        String originalHash = original.get("content_hash").stringValue();

        String body = review(caseId, reviewerToken, verification(sourceId, "CONFIRMED", "承运商系统复核显示该件确实停留在分拨中心"))
                .expectStatus()
                .isOk()
                .expectBody(String.class)
                .returnResult()
                .getResponseBody();
        JsonNode appended = MAPPER.readTree(body);

        assertThat(appended.properties().stream().map(Map.Entry::getKey))
                .as("the answer is the contract's ReviewedEvidenceResponse, and a revocation that did not"
                        + " happen is absent rather than invented")
                .containsExactlyInAnyOrder("case_id", "evidence_id", "input_revision", "case_version");
        assertThat(appended.get("case_id").stringValue()).isEqualTo(caseId);
        assertThat(appended.get("input_revision").asInt())
                .isEqualTo(before.get("case").get("input_revision").asInt() + 1);
        assertThat(appended.get("case_version").asLong())
                .isEqualTo(before.get("case").get("version").asLong() + 1);
        assertThat(appended.get("evidence_id").stringValue()).isNotBlank();

        JsonNode after = MAPPER.readTree(view(caseId, reviewerToken)).get("evidence");
        assertThat(after.size()).as("the material is added to, not replaced").isEqualTo(2);
        JsonNode unchanged = after.get(0);
        assertThat(unchanged.get("observation_id").stringValue()).isEqualTo(sourceId);
        assertThat(unchanged.get("content").stringValue()).isEqualTo(statement);
        assertThat(unchanged.get("content_hash").stringValue())
                .as("the verified record was not rewritten")
                .isEqualTo(originalHash);
        assertThat(unchanged.get("input_revision").asInt()).isEqualTo(2);

        JsonNode recorded = after.get(1);
        assertThat(recorded.properties().stream().map(Map.Entry::getKey))
                .containsExactlyInAnyOrder(
                        "observation_id",
                        "source_ref",
                        "source_version",
                        "content_hash",
                        "evidence_kind",
                        "content",
                        "input_revision",
                        "observed_at",
                        "appended_by",
                        "appended_role",
                        "reviewed_evidence_id",
                        "verification_result");
        assertThat(recorded.get("evidence_kind").stringValue()).isEqualTo("REVIEWER_VERIFICATION");
        assertThat(recorded.get("content").stringValue()).contains("分拨中心");
        assertThat(recorded.get("reviewed_evidence_id").stringValue()).isEqualTo(sourceId);
        assertThat(recorded.get("verification_result").stringValue()).isEqualTo("CONFIRMED");
        assertThat(recorded.get("appended_by").stringValue()).isEqualTo("demo-reviewer");
        assertThat(recorded.get("appended_role").stringValue()).isEqualTo("REVIEWER");
        assertThat(recorded.get("source_ref").stringValue()).isEqualTo("evidence:" + sourceId);
        assertThat(recorded.get("source_version").stringValue())
                .as("the citation says which revision of the record was verified")
                .isEqualTo("2");
        assertThat(recorded.get("observed_at").stringValue()).endsWith("Z");

        assertThat(view(caseId, reviewerToken))
                .as("the trajectory states the conclusion instead of only that something was recorded")
                .contains("人工核验：已确认该材料");
        assertThat(evidenceRows(caseId, "REVIEWER_VERIFICATION")).isEqualTo(1);
        Map<String, Object> current =
                jdbc.queryForMap("SELECT status, input_revision FROM aftersale_case WHERE case_id = ?", caseId);
        assertThat(current.get("status"))
                .as("new verification hands the new revision back to investigation")
                .isEqualTo("QUEUED");
        assertThat(jdbc.queryForObject(
                        "SELECT COUNT(*) FROM agent_binding WHERE case_id = ? AND input_revision = ?"
                                + " AND run_id = ? AND dispatch_status = 'PENDING'",
                        Integer.class,
                        caseId,
                        current.get("input_revision"),
                        AgentRunId.forRevision(caseId, (Integer) current.get("input_revision"))))
                .as("the revision move durably schedules one fresh run")
                .isEqualTo(1);
    }

    @Test
    @DisplayName("a refutation is recorded the same way; with no approval on the case there is nothing to retire")
    void aRefutationIsRecorded() {
        String customerToken = customer("M-1001", "B-legacy-60865438438feefa1dfbc0ce3d07ba2cb1b09a80");
        String reviewerToken = reviewer("demo-reviewer", "M-1001");
        String caseId = openCase("M-1001", "B-legacy-60865438438feefa1dfbc0ce3d07ba2cb1b09a80", LINE);
        String sourceId = appendStatement(caseId, customerToken, "包裹已经收到了");

        String body = review(caseId, reviewerToken, verification(sourceId, "REFUTED", "承运商记录显示该件仍在运输中"))
                .expectStatus()
                .isOk()
                .expectBody(String.class)
                .returnResult()
                .getResponseBody();

        assertThat(MAPPER.readTree(body).has("revoked_authorization_id"))
                .as("no authorisation exists to revoke, and the answer says so by saying nothing")
                .isFalse();
        assertThat(view(caseId, reviewerToken)).contains("人工核验：已否证该材料");
        JsonNode recorded =
                MAPPER.readTree(view(caseId, reviewerToken)).get("evidence").get(1);
        assertThat(recorded.get("verification_result").stringValue()).isEqualTo("REFUTED");
    }

    @Test
    @DisplayName("a record of another case, or a record that does not exist, is refused")
    void theNamedRecordHasToBeInThisCase() {
        String customerToken = customer("M-1001", "B-legacy-60865438438feefa1dfbc0ce3d07ba2cb1b09a80");
        String reviewerToken = reviewer("demo-reviewer", "M-1001");
        String first = openCase("M-1001", "B-legacy-60865438438feefa1dfbc0ce3d07ba2cb1b09a80", LINE);
        String second = openCase("M-1001", "B-legacy-60865438438feefa1dfbc0ce3d07ba2cb1b09a80", "7002");
        String elsewheres = appendStatement(first, customerToken, "包裹在分拨中心停了七天");

        String unknown = review(
                        second,
                        reviewerToken,
                        verification("0f0f0f0f-1111-4222-8333-444444444444", "CONFIRMED", "看起来没问题"))
                .expectStatus()
                .isEqualTo(422)
                .expectBody(String.class)
                .returnResult()
                .getResponseBody();
        assertThat(MAPPER.readTree(unknown).get("message").stringValue())
                .as("the message names the member the caller got wrong")
                .contains("source_evidence_id");

        String crossCase = review(second, reviewerToken, verification(elsewheres, "CONFIRMED", "看起来没问题"))
                .expectStatus()
                .isEqualTo(422)
                .expectBody(String.class)
                .returnResult()
                .getResponseBody();
        assertThat(MAPPER.readTree(crossCase).get("message").stringValue())
                .as("material of another case is not verifiable from here, and the answer says which id")
                .contains(elsewheres);

        assertThat(evidenceRows(second, "REVIEWER_VERIFICATION"))
                .as("a refused message records nothing")
                .isZero();
        assertThat(jdbc.queryForObject(
                        "SELECT input_revision FROM aftersale_case WHERE case_id = ?", Integer.class, second))
                .as("and does not move the revision it was refused at")
                .isEqualTo(1);
    }

    @Test
    @DisplayName("material is verified, not the record of somebody's verification of it")
    void aVerificationOfAVerificationIsRefused() {
        String customerToken = customer("M-1001", "B-legacy-60865438438feefa1dfbc0ce3d07ba2cb1b09a80");
        String reviewerToken = reviewer("demo-reviewer", "M-1001");
        String caseId = openCase("M-1001", "B-legacy-60865438438feefa1dfbc0ce3d07ba2cb1b09a80", LINE);
        String sourceId = appendStatement(caseId, customerToken, "包裹在分拨中心停了七天");
        String verificationId = MAPPER.readTree(
                        review(caseId, reviewerToken, verification(sourceId, "CONFIRMED", "承运商记录一致"))
                                .expectStatus()
                                .isOk()
                                .expectBody(String.class)
                                .returnResult()
                                .getResponseBody())
                .get("evidence_id")
                .stringValue();

        String body = review(caseId, reviewerToken, verification(verificationId, "CONFIRMED", "再核一次"))
                .expectStatus()
                .isEqualTo(422)
                .expectBody(String.class)
                .returnResult()
                .getResponseBody();

        assertThat(MAPPER.readTree(body).get("message").stringValue()).contains("itself a verification");
        assertThat(evidenceRows(caseId, "REVIEWER_VERIFICATION")).isEqualTo(1);
    }

    @Test
    @DisplayName("a customer records statements, not verifications of them")
    void aCustomerMayNotRecordAVerification() {
        String customerToken = customer("M-1001", "B-legacy-60865438438feefa1dfbc0ce3d07ba2cb1b09a80");
        String caseId = openCase("M-1001", "B-legacy-60865438438feefa1dfbc0ce3d07ba2cb1b09a80", LINE);
        String sourceId = appendStatement(caseId, customerToken, "包裹在分拨中心停了七天");

        String body = review(caseId, customerToken, verification(sourceId, "CONFIRMED", "我自己确认一下"))
                .expectStatus()
                .isEqualTo(403)
                .expectBody(String.class)
                .returnResult()
                .getResponseBody();

        assertThat(MAPPER.readTree(body).get("code").stringValue()).isEqualTo("FORBIDDEN_SCOPE");
        assertThat(evidenceRows(caseId, "REVIEWER_VERIFICATION")).isZero();
    }

    @Test
    @DisplayName("another merchant's reviewer is answered 404, the same answer as a case that does not exist")
    void anotherMerchantSeesNothing() {
        String customerToken = customer("M-1001", "B-legacy-60865438438feefa1dfbc0ce3d07ba2cb1b09a80");
        String caseId = openCase("M-1001", "B-legacy-60865438438feefa1dfbc0ce3d07ba2cb1b09a80", LINE);
        String sourceId = appendStatement(caseId, customerToken, "包裹在分拨中心停了七天");

        String body = review(
                        caseId, reviewer("demo-reviewer-m2", "M-1002"), verification(sourceId, "CONFIRMED", "不是我的工单"))
                .expectStatus()
                .isNotFound()
                .expectBody(String.class)
                .returnResult()
                .getResponseBody();

        assertThat(MAPPER.readTree(body).get("code").stringValue()).isEqualTo("NOT_FOUND");
    }

    @Test
    @DisplayName("a case that already ended refuses verification, and says which ending it was")
    void anEndedCaseRefusesVerification() {
        String customerToken = customer("M-1001", "B-legacy-60865438438feefa1dfbc0ce3d07ba2cb1b09a80");
        String reviewerToken = reviewer("demo-reviewer", "M-1001");
        String caseId = openCase("M-1001", "B-legacy-60865438438feefa1dfbc0ce3d07ba2cb1b09a80", LINE);
        String sourceId = appendStatement(caseId, customerToken, "包裹在分拨中心停了七天");
        rest.post()
                .uri("/api/v1/cases/" + caseId + "/cancel")
                .header(HttpHeaders.AUTHORIZATION, "Bearer " + customerToken)
                .contentType(MediaType.APPLICATION_JSON)
                .body(Map.of("reason", "不需要了"))
                .headers(h -> addReviewHeaders(h, caseId))
                .exchange()
                .expectStatus()
                .isOk();

        String body = review(caseId, reviewerToken, verification(sourceId, "CONFIRMED", "太晚了"))
                .expectStatus()
                .isEqualTo(409)
                .expectBody(String.class)
                .returnResult()
                .getResponseBody();

        assertThat(MAPPER.readTree(body).get("message").stringValue()).contains("CANCELLED");
        assertThat(evidenceRows(caseId, "REVIEWER_VERIFICATION")).isZero();
    }

    @Test
    @DisplayName("a case at the view's declared bound refuses more material instead of hiding the oldest")
    void aFullCaseRefusesMoreMaterial() {
        String customerToken = customer("M-1001", "B-legacy-60865438438feefa1dfbc0ce3d07ba2cb1b09a80");
        String reviewerToken = reviewer("demo-reviewer", "M-1001");
        String caseId = openCase("M-1001", "B-legacy-60865438438feefa1dfbc0ce3d07ba2cb1b09a80", LINE);
        String sourceId = appendStatement(caseId, customerToken, "包裹在分拨中心停了七天");

        // Fill the case up to the contract's maxItems, the way a long conversation would. The bound is the
        // case view's, so a case that reached it must refuse rather than let the oldest record fall out of
        // the only surface that serves material.
        Instant now = Instant.parse("2026-09-19T02:00:00Z");
        for (int index = 0; index < CaseEvidenceService.MAX_RECORDS - 1; index++) {
            jdbc.update(
                    "INSERT INTO case_evidence (case_id, evidence_id, source_type, source_ref, source_version,"
                            + " content_hash, input_revision, observed_at, content, appended_by, appended_role,"
                            + " created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                    caseId,
                    java.util.UUID.randomUUID().toString(),
                    "CUSTOMER_STATEMENT",
                    "customer:B-legacy-60865438438feefa1dfbc0ce3d07ba2cb1b09a80",
                    "2",
                    "a".repeat(64),
                    2,
                    java.sql.Timestamp.from(now),
                    "补充说明 " + index,
                    "demo-customer",
                    "CUSTOMER",
                    java.sql.Timestamp.from(now));
        }
        assertThat(jdbc.queryForObject("SELECT COUNT(*) FROM case_evidence WHERE case_id = ?", Integer.class, caseId))
                .isEqualTo(CaseEvidenceService.MAX_RECORDS);

        String body = review(caseId, reviewerToken, verification(sourceId, "CONFIRMED", "第 65 条"))
                .expectStatus()
                .isEqualTo(422)
                .expectBody(String.class)
                .returnResult()
                .getResponseBody();

        assertThat(MAPPER.readTree(body).get("message").stringValue())
                .contains(String.valueOf(CaseEvidenceService.MAX_RECORDS));
        assertThat(jdbc.queryForObject("SELECT COUNT(*) FROM case_evidence WHERE case_id = ?", Integer.class, caseId))
                .isEqualTo(CaseEvidenceService.MAX_RECORDS);
    }

    @Test
    @DisplayName("a request that is not a verification at all is refused with a message naming what is wrong")
    void aMalformedRequestIsRefused() {
        String customerToken = customer("M-1001", "B-legacy-60865438438feefa1dfbc0ce3d07ba2cb1b09a80");
        String reviewerToken = reviewer("demo-reviewer", "M-1001");
        String caseId = openCase("M-1001", "B-legacy-60865438438feefa1dfbc0ce3d07ba2cb1b09a80", LINE);
        String sourceId = appendStatement(caseId, customerToken, "包裹在分拨中心停了七天");

        Map<String, Map<String, Object>> refused = Map.of(
                "unknown result", verification(sourceId, "MAYBE", "说不清"),
                "not a uuid", verification("ev-1", "CONFIRMED", "拿错 id 了"),
                "blank reason", verification(sourceId, "CONFIRMED", " "));

        for (Map.Entry<String, Map<String, Object>> each : refused.entrySet()) {
            String body = review(caseId, reviewerToken, each.getValue())
                    .expectStatus()
                    .isEqualTo(422)
                    .expectBody(String.class)
                    .returnResult()
                    .getResponseBody();
            JsonNode error = MAPPER.readTree(body);
            assertThat(error.get("code").stringValue()).as(each.getKey()).isEqualTo("SEMANTIC_INVALID");
            assertThat(error.get("message").stringValue()).as(each.getKey()).isNotBlank();
        }

        assertThat(evidenceRows(caseId, "REVIEWER_VERIFICATION")).isZero();
    }
}
