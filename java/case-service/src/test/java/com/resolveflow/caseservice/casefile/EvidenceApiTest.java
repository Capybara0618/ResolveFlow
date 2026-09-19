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
 * {@code POST /api/v1/cases/{case_id}/evidence} (docs/core-contracts.md:30).
 *
 * <p>The rules under test are the ones a reviewer would ask about: material is added rather than
 * replaced, the revision is the server's, provenance decides who may say what, and once the case is
 * executing the input is closed. Most assertions read the database as well as the response, because "the
 * revision bumped" and "a second record exists" are claims about what was stored.
 */
@AutoConfigureRestTestClient
class EvidenceApiTest extends CaseDatabaseTest {

    private static final ObjectMapper MAPPER = new ObjectMapper();
    private static final String LINE = "7001";

    @Autowired
    RestTestClient rest;

    @Autowired
    StubCommerce commerce;

    @Autowired
    JwtCodec jwtCodec;

    @Autowired
    CaseRepository cases;

    @Autowired
    JdbcTemplate jdbc;

    @Autowired
    CaseEvidenceService evidenceService;

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
        jdbc.execute("DELETE FROM case_evidence");
        jdbc.execute("DELETE FROM request_idempotency");
        jdbc.execute("DELETE FROM case_timeline");
        jdbc.execute("DELETE FROM active_case_slot");
        jdbc.execute("DELETE FROM case_requested_action");
        jdbc.execute("DELETE FROM aftersale_case");
        commerce.lineVisible = true;
    }

    private static String token(JwtCodec codec, String user, String merchant, Role role, String customer) {
        return codec.issue(new AuthenticatedPrincipal(user, merchant, role, customer), Instant.now());
    }

    private String customer() {
        return token(jwtCodec, "demo-customer", "M-1001", Role.CUSTOMER, "C-2002");
    }

    private String openCase() {
        return openCase(LINE);
    }

    /** A second case needs a second line: one active case per line is the rule under test earlier. */
    private String openCase(String line) {
        String body = rest.post()
                .uri("/api/v1/cases")
                .header(HttpHeaders.AUTHORIZATION, "Bearer " + customer())
                .header("Idempotency-Key", "evidence-key-" + System.nanoTime())
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

    private RestTestClient.ResponseSpec append(String caseId, String token, Map<String, Object> body) {
        RestTestClient.RequestHeadersSpec<?> request = rest.post()
                .uri("/api/v1/cases/" + caseId + "/evidence")
                .contentType(MediaType.APPLICATION_JSON)
                .body(body);
        if (token != null) {
            request = request.header(HttpHeaders.AUTHORIZATION, "Bearer " + token);
        }
        return request.exchange();
    }

    private static Map<String, Object> statement(String text) {
        Map<String, Object> body = new HashMap<>();
        body.put("text", text);
        body.put("evidence_kind", "CUSTOMER_STATEMENT");
        return body;
    }

    private List<Map<String, Object>> evidenceRows(String caseId) {
        return jdbc.queryForList("SELECT * FROM case_evidence WHERE case_id = ? ORDER BY input_revision", caseId);
    }

    @Test
    @DisplayName("a customer's statement bumps the revision and is stored with its hash")
    void appendingBumpsTheRevision() {
        String caseId = openCase();

        String body = append(caseId, customer(), statement("小区驿站确认7天内没有任何到件记录"))
                .expectStatus()
                .isOk()
                .expectBody(String.class)
                .returnResult()
                .getResponseBody();

        JsonNode json = MAPPER.readTree(body);
        assertThat(json.properties().stream().map(Map.Entry::getKey))
                .containsExactlyInAnyOrder("case_id", "input_revision", "version");
        assertThat(json.get("case_id").stringValue()).isEqualTo(caseId);
        assertThat(json.get("input_revision").asInt()).isEqualTo(2);
        assertThat(json.get("version").asInt()).isEqualTo(2);

        List<Map<String, Object>> rows = evidenceRows(caseId);
        assertThat(rows).hasSize(1);
        assertThat(rows.get(0).get("source_type")).isEqualTo("CUSTOMER_STATEMENT");
        assertThat(rows.get(0).get("input_revision")).isEqualTo(2);
        assertThat(rows.get(0).get("source_ref")).isEqualTo("customer:C-2002");
        assertThat(rows.get(0).get("content").toString()).contains("小区驿站");
        assertThat(rows.get(0).get("content_hash").toString()).hasSize(64);
        assertThat(rows.get(0).get("appended_role")).isEqualTo("CUSTOMER");

        // the case itself moved, and both numbers moved together
        Map<String, Object> row = jdbc.queryForMap(
                "SELECT input_revision, version, status FROM aftersale_case WHERE case_id = ?", caseId);
        assertThat(row.get("input_revision")).isEqualTo(2);
        assertThat(row.get("version")).as("BIGINT comes back as a Long").isEqualTo(2L);

        // and the trajectory says why the revision moved
        List<Map<String, Object>> timeline = jdbc.queryForList(
                "SELECT kind, input_revision FROM case_timeline WHERE case_id = ? ORDER BY sequence", caseId);
        assertThat(timeline).hasSize(2);
        assertThat(timeline.get(1).get("kind")).isEqualTo("EVIDENCE_APPENDED");
        assertThat(timeline.get(1).get("input_revision")).isEqualTo(2);

        String snapshot = rest.get()
                .uri("/api/v1/cases/" + caseId)
                .header(HttpHeaders.AUTHORIZATION, "Bearer " + customer())
                .exchange()
                .expectStatus()
                .isOk()
                .expectBody(String.class)
                .returnResult()
                .getResponseBody();
        JsonNode events = MAPPER.readTree(snapshot).get("timeline");
        assertThat(events.get(1).get("type").stringValue()).isEqualTo("EVIDENCE_APPENDED");
        assertThat(events.get(1).get("summary").stringValue()).isEqualTo("客户补充了材料");
        assertThat(events.get(1).get("revision").asInt()).isEqualTo(2);
    }

    @Test
    @DisplayName("material is appended, never replaced: two submissions are two records")
    void materialIsNeverOverwritten() {
        String caseId = openCase();

        append(caseId, customer(), statement("第一次说明")).expectStatus().isOk();
        String second = append(caseId, customer(), statement("第二次说明，纠正上文"))
                .expectStatus()
                .isOk()
                .expectBody(String.class)
                .returnResult()
                .getResponseBody();

        assertThat(MAPPER.readTree(second).get("input_revision").asInt()).isEqualTo(3);

        List<Map<String, Object>> rows = evidenceRows(caseId);
        assertThat(rows).hasSize(2);
        assertThat(rows.get(0).get("content"))
                .as("the earlier statement is still there")
                .isEqualTo("第一次说明");
        assertThat(rows.get(1).get("content")).isEqualTo("第二次说明，纠正上文");
        assertThat(rows.get(0).get("evidence_id")).isNotEqualTo(rows.get(1).get("evidence_id"));
        assertThat(rows.get(0).get("content_hash")).isNotEqualTo(rows.get(1).get("content_hash"));
    }

    @Test
    @DisplayName("no spelling of the request writes into a past revision")
    void theRevisionIsTheServersDecision() {
        String caseId = openCase();
        append(caseId, customer(), statement("第一次说明")).expectStatus().isOk();

        // A body that carries a revision is not a request to write at that revision: it is an unknown
        // member, and it is refused rather than quietly ignored.
        Map<String, Object> withRevision = statement("试图写回旧 revision");
        withRevision.put("input_revision", 1);
        append(caseId, customer(), withRevision)
                .expectStatus()
                .isBadRequest()
                .expectBody(String.class)
                .value(body -> assertThat(MAPPER.readTree(body).get("code").stringValue())
                        .isEqualTo("INVALID_ARGUMENT"));

        assertThat(evidenceRows(caseId)).hasSize(1);
        assertThat(jdbc.queryForObject(
                        "SELECT MAX(input_revision) FROM case_evidence WHERE case_id = ?", Integer.class, caseId))
                .isEqualTo(2);
        assertThat(jdbc.queryForObject(
                        "SELECT COUNT(*) FROM case_evidence WHERE case_id = ? AND input_revision = 1",
                        Integer.class,
                        caseId))
                .as("revision 1 is the case's creation and can never hold material")
                .isZero();
    }

    @Test
    @DisplayName("provenance decides who may submit what")
    void provenanceDecidesWhoMaySubmitWhat() {
        String caseId = openCase();
        String reviewer = token(jwtCodec, "demo-reviewer", "M-1001", Role.REVIEWER, null);
        String otherCustomer = token(jwtCodec, "demo-customer-2", "M-1001", Role.CUSTOMER, "C-2003");

        // A machine-read fact is not a client's claim, whoever the client is.
        for (String kind : List.of("SHIPMENT", "PAYMENT_LEDGER", "ORDER_LINE", "POLICY_RULE")) {
            Map<String, Object> body = statement("我说它发过货");
            body.put("evidence_kind", kind);
            append(caseId, customer(), body)
                    .expectStatus()
                    .isForbidden()
                    .expectBody(String.class)
                    .value(error -> assertThat(
                                    MAPPER.readTree(error).get("code").stringValue())
                            .isEqualTo("FORBIDDEN_SCOPE"));
        }

        // A customer statement comes from the case's customer.
        append(caseId, reviewer, statement("代替客户说一句")).expectStatus().isForbidden();
        append(caseId, otherCustomer, statement("我不是这单的客户")).expectStatus().isNotFound();

        // Merchant staff record their own verification, and that is a different record.
        Map<String, Object> verification = new HashMap<>();
        verification.put("text", "已电话联系客户核实地址");
        verification.put("evidence_kind", "REVIEWER_VERIFICATION");
        append(caseId, reviewer, verification).expectStatus().isOk();

        List<Map<String, Object>> rows = evidenceRows(caseId);
        assertThat(rows).hasSize(1);
        assertThat(rows.get(0).get("source_type")).isEqualTo("REVIEWER_VERIFICATION");
        assertThat(rows.get(0).get("source_ref")).isEqualTo("reviewer:demo-reviewer");
        assertThat(rows.get(0).get("appended_role")).isEqualTo("REVIEWER");
    }

    @Test
    @DisplayName("once the case is executing the input is closed")
    void aConsumedInputCannotChange() {
        String caseId = openCase();
        // EXECUTING is reachable only after the authorisation is consumed (docs/domain-model.md:55);
        // C03 wires the consumption itself, so the state is set here directly.
        jdbc.update("UPDATE aftersale_case SET status = 'EXECUTING' WHERE case_id = ?", caseId);

        append(caseId, customer(), statement("执行中再补一句"))
                .expectStatus()
                .isEqualTo(409)
                .expectBody(String.class)
                .value(body -> {
                    JsonNode error = MAPPER.readTree(body);
                    assertThat(error.get("code").stringValue()).isEqualTo("STATE_CONFLICT");
                    // The words matter as much as the code: this case is running, not ended.
                    assertThat(error.get("message").stringValue()).contains("already executing");
                });

        assertThat(evidenceRows(caseId)).isEmpty();
        assertThat(jdbc.queryForObject(
                        "SELECT input_revision FROM aftersale_case WHERE case_id = ?", Integer.class, caseId))
                .as("a refused append must not move the revision")
                .isEqualTo(1);
    }

    @Test
    @DisplayName("a case at WAITING_CUSTOMER goes back to the queue; other states keep theirs")
    void anAnswerReturnsTheCaseToTheQueue() {
        String caseId = openCase();
        jdbc.update("UPDATE aftersale_case SET status = 'WAITING_CUSTOMER' WHERE case_id = ?", caseId);
        append(caseId, customer(), statement("补充说明")).expectStatus().isOk();
        assertThat(jdbc.queryForObject("SELECT status FROM aftersale_case WHERE case_id = ?", String.class, caseId))
                .isEqualTo("QUEUED");

        // Material that arrives while a proposal is under review bumps the revision without pretending
        // the case went back to the queue.
        String other = openCase("7002");
        jdbc.update("UPDATE aftersale_case SET status = 'PENDING_REVIEW' WHERE case_id = ?", other);
        append(other, customer(), statement("又想起一件事")).expectStatus().isOk();
        Map<String, Object> row =
                jdbc.queryForMap("SELECT status, input_revision FROM aftersale_case WHERE case_id = ?", other);
        assertThat(row.get("status")).isEqualTo("PENDING_REVIEW");
        assertThat(row.get("input_revision")).isEqualTo(2);
    }

    @Test
    @DisplayName("a body that is well formed but means nothing is 422, and needs a token at all")
    void semanticAndAuthenticationRefusals() {
        String caseId = openCase();

        Map<String, Object> blank = statement("   ");
        append(caseId, customer(), blank).expectStatus().isEqualTo(422);

        Map<String, Object> unknownKind = statement("随便写的");
        unknownKind.put("evidence_kind", "MY_OWN_IDEA");
        append(caseId, customer(), unknownKind)
                .expectStatus()
                .isEqualTo(422)
                .expectBody(String.class)
                .value(body -> assertThat(MAPPER.readTree(body).get("code").stringValue())
                        .isEqualTo("SEMANTIC_INVALID"));

        Map<String, Object> noKind = new HashMap<>();
        noKind.put("text", "缺少类型");
        append(caseId, customer(), noKind).expectStatus().isEqualTo(422);

        Map<String, Object> tooLong = statement("x".repeat(8001));
        append(caseId, customer(), tooLong).expectStatus().isEqualTo(422);

        append(caseId, null, statement("没有 token"))
                .expectStatus()
                .isUnauthorized()
                .expectBody(String.class)
                .value(body -> assertThat(MAPPER.readTree(body).get("code").stringValue())
                        .isEqualTo("UNAUTHENTICATED"));

        append("00000000-0000-4000-8000-00000000dead", customer(), statement("不存在的工单"))
                .expectStatus()
                .isNotFound();

        assertThat(evidenceRows(caseId)).isEmpty();
    }

    @Test
    @DisplayName("four submissions arriving together get four revisions, not one shared one")
    void concurrentAppendsDoNotShareARevision() throws Exception {
        String caseId = openCase();
        AuthenticatedPrincipal principal =
                new AuthenticatedPrincipal("demo-customer", "M-1001", Role.CUSTOMER, "C-2002");
        int threads = 4;
        var pool = java.util.concurrent.Executors.newFixedThreadPool(threads);
        var start = new java.util.concurrent.CountDownLatch(1);
        List<java.util.concurrent.Future<EvidenceSubmissionResponse>> futures = new java.util.ArrayList<>();
        for (int i = 0; i < threads; i++) {
            int index = i;
            futures.add(pool.submit(() -> {
                start.await();
                return evidenceService.append(
                        principal, caseId, new EvidenceAppendRequest(null, "并发说明 " + index, "CUSTOMER_STATEMENT"));
            }));
        }
        start.countDown();
        List<Integer> revisions = new java.util.ArrayList<>();
        for (var future : futures) {
            revisions.add(future.get(30, java.util.concurrent.TimeUnit.SECONDS).inputRevision());
        }
        pool.shutdown();

        assertThat(revisions)
                .as("every submission claims a revision of its own")
                .doesNotHaveDuplicates();
        assertThat(revisions).containsExactlyInAnyOrder(2, 3, 4, 5);
        assertThat(evidenceRows(caseId)).as("four submissions are four records").hasSize(threads);
        assertThat(jdbc.queryForObject(
                        "SELECT COUNT(DISTINCT input_revision) FROM case_evidence WHERE case_id = ?",
                        Integer.class,
                        caseId))
                .isEqualTo(threads);
        assertThat(jdbc.queryForObject(
                        "SELECT input_revision FROM aftersale_case WHERE case_id = ?", Integer.class, caseId))
                .as("the case moved exactly once per submission")
                .isEqualTo(1 + threads);
    }
}
