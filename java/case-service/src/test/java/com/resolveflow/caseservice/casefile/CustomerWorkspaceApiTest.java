package com.resolveflow.caseservice.casefile;

import static org.assertj.core.api.Assertions.assertThat;

import com.resolveflow.caseservice.CaseDatabaseTest;
import com.resolveflow.shared.security.AuthenticatedPrincipal;
import com.resolveflow.shared.security.JwtCodec;
import com.resolveflow.shared.security.Role;
import java.time.Instant;
import java.util.Map;
import java.util.UUID;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.resttestclient.autoconfigure.AutoConfigureRestTestClient;
import org.springframework.http.MediaType;
import org.springframework.test.web.servlet.client.RestTestClient;
import tools.jackson.databind.ObjectMapper;

@AutoConfigureRestTestClient
class CustomerWorkspaceApiTest extends CaseDatabaseTest {
    @Autowired
    RestTestClient rest;

    @Autowired
    JwtCodec codec;

    @Autowired
    CaseRepository cases;

    @Autowired
    ProposalRepository proposals;

    @Autowired
    AuthorizationRepository authorizations;

    private final ObjectMapper json = new ObjectMapper();

    @BeforeEach
    void clear() {
        deleteAllCaseData(jdbc);
    }

    private String token(String username, String merchant, String customer) {
        return codec.issue(
                new AuthenticatedPrincipal(
                        username, merchant, customer == null ? Role.REVIEWER : Role.CUSTOMER, customer),
                Instant.now());
    }

    private String own() {
        return token("demo-customer", "M-1001", "C-2002");
    }

    private String row(String merchant, String customer, String status, Instant time) {
        String id = UUID.randomUUID().toString();
        cases.insertCase(
                id,
                merchant,
                customer,
                UUID.randomUUID().toString(),
                "line-" + id,
                "原始申请",
                status,
                1,
                1,
                null,
                time,
                time);
        return id;
    }

    private String read(String path, String token) {
        return rest.get()
                .uri(path)
                .header("Authorization", "Bearer " + token)
                .exchange()
                .expectStatus()
                .isOk()
                .expectBody(String.class)
                .returnResult()
                .getResponseBody();
    }

    @Test
    void listIsOwnedAndSupportsStages() {
        String mine = row("M-1001", "C-2002", "WAITING_CUSTOMER", Instant.now());
        String another = row("M-1001", "C-2003", "WAITING_CUSTOMER", Instant.now());
        String tenant = row("M-1002", "C-2004", "WAITING_CUSTOMER", Instant.now());
        String closed = row("M-1001", "C-2002", "CANCELLED", Instant.now());
        String body = read("/api/v1/customer/cases?view=WAITING", own());
        assertThat(body).contains(mine).doesNotContain(another, tenant, closed, "merchant_id", "customer_id");
        assertThat(read("/api/v1/customer/cases?view=CLOSED", own()))
                .contains(closed)
                .doesNotContain(mine);
    }

    @Test
    void cursorKeepsMicrosecondsAndRejectsChangedFilter() {
        Instant time = Instant.parse("2026-10-01T10:00:00.123456Z");
        String first = row("M-1001", "C-2002", "QUEUED", time.plusNanos(1000));
        String second = row("M-1001", "C-2002", "QUEUED", time);
        var page = json.readTree(read("/api/v1/customer/cases?limit=1", own()));
        assertThat(page.get("items").get(0).get("case_id").stringValue()).isEqualTo(first);
        String cursor = page.get("page").get("next_cursor").stringValue();
        assertThat(read("/api/v1/customer/cases?limit=1&cursor=" + cursor, own()))
                .contains(second)
                .doesNotContain(first);
        rest.get()
                .uri("/api/v1/customer/cases?view=CLOSED&cursor=" + cursor)
                .header("Authorization", "Bearer " + own())
                .exchange()
                .expectStatus()
                .isBadRequest();
    }

    @Test
    void detailIsPrivateAndContainsNoStaffProjection() {
        String id = row("M-1001", "C-2002", "PENDING_REVIEW", Instant.now());
        cases.insertTimeline(
                id,
                UUID.randomUUID().toString(),
                1,
                "PROPOSAL_READY",
                "{\"authored_by\":\"private-worker\",\"refusal_reason\":\"private-tool-error\"}",
                Instant.now(),
                1);
        String body = read("/api/v1/customer/cases/" + id, own());
        assertThat(body)
                .contains("原始申请", "allowed_actions", "materials", "questions", "result")
                .doesNotContain(
                        "private-worker",
                        "private-tool-error",
                        "proposal",
                        "authorization",
                        "policy_refs",
                        "run_id",
                        "source_ref");
        for (String other : new String[] {
            token("demo-customer-2", "M-1001", "C-2003"), token("demo-customer-m2", "M-1002", "C-2004")
        })
            rest.get()
                    .uri("/api/v1/customer/cases/" + id)
                    .header("Authorization", "Bearer " + other)
                    .exchange()
                    .expectStatus()
                    .isNotFound();
        rest.get()
                .uri("/api/v1/customer/cases")
                .header("Authorization", "Bearer " + token("demo-reviewer", "M-1001", null))
                .exchange()
                .expectStatus()
                .isForbidden();
    }

    @Test
    void directAnswerIsVersionedAndAssociatesCurrentQuestion() {
        String id = row("M-1001", "C-2002", "WAITING_CUSTOMER", Instant.now());
        String q = UUID.randomUUID().toString();
        cases.insertTimeline(
                id,
                UUID.randomUUID().toString(),
                1,
                "QUESTION_REQUIRED",
                "{\"question_id\":\"" + q + "\",\"questions\":[{\"prompt\":\"是否联系承运商？\"}]}",
                Instant.now(),
                1);
        rest.post()
                .uri("/api/v1/customer/cases/" + id + "/answers")
                .header("Authorization", "Bearer " + own())
                .header("If-Match", "\"1\"")
                .contentType(MediaType.APPLICATION_JSON)
                .body(Map.of("question_id", q, "text", "承运商已回复包裹丢失"))
                .exchange()
                .expectStatus()
                .isOk();
        String body = read("/api/v1/customer/cases/" + id, own());
        assertThat(body).contains("QUEUED", "ANSWERED", "承运商已回复包裹丢失");
        assertThat(jdbc.queryForObject("SELECT question_id FROM case_evidence WHERE case_id=?", String.class, id))
                .isEqualTo(q);
        assertThat(jdbc.queryForObject(
                        "SELECT COUNT(*) FROM agent_binding WHERE case_id=? AND input_revision=2", Integer.class, id))
                .isEqualTo(1);
        rest.post()
                .uri("/api/v1/customer/cases/" + id + "/answers")
                .header("Authorization", "Bearer " + own())
                .header("If-Match", "\"1\"")
                .contentType(MediaType.APPLICATION_JSON)
                .body(Map.of("question_id", q, "text", "重复"))
                .exchange()
                .expectStatus()
                .isEqualTo(409);
    }

    @Test
    void expiredQuestionCannotBeAnsweredThroughEitherCustomerEntry() {
        String id = row("M-1001", "C-2002", "WAITING_CUSTOMER", Instant.now());
        String q = UUID.randomUUID().toString();
        cases.insertTimeline(
                id,
                UUID.randomUUID().toString(),
                1,
                "QUESTION_REQUIRED",
                "{\"question_id\":\"" + q + "\",\"questions\":[{\"prompt\":\"补充说明\"}]}",
                Instant.now().minus(java.time.Duration.ofHours(73)),
                1);
        var detail = json.readTree(read("/api/v1/customer/cases/" + id, own()));
        assertThat(detail.get("questions").get(0).get("status").stringValue()).isEqualTo("EXPIRED");
        assertThat(detail.get("allowed_actions").toString()).doesNotContain("ANSWER", "APPEND_EVIDENCE");
        rest.post()
                .uri("/api/v1/customer/cases/" + id + "/answers")
                .header("Authorization", "Bearer " + own())
                .header("If-Match", "\"1\"")
                .contentType(MediaType.APPLICATION_JSON)
                .body(Map.of("question_id", q, "text", "过期回答"))
                .exchange()
                .expectStatus()
                .isEqualTo(409);
        rest.post()
                .uri("/api/v1/cases/" + id + "/evidence")
                .header("Authorization", "Bearer " + own())
                .contentType(MediaType.APPLICATION_JSON)
                .body(Map.of("question_id", q, "text", "旧入口绕过期限", "evidence_kind", "CUSTOMER_STATEMENT"))
                .exchange()
                .expectStatus()
                .isEqualTo(409);
        assertThat(jdbc.queryForObject("SELECT COUNT(*) FROM case_evidence WHERE case_id=?", Integer.class, id))
                .isZero();
    }

    @Test
    void consumedInputIsReadOnlyEvenWhenItReturnsToReviewOrWaiting() {
        String id = row("M-1001", "C-2002", "PENDING_REVIEW", Instant.now());
        String proposal = UUID.randomUUID().toString(),
                operation = UUID.randomUUID().toString();
        proposals.insert(
                proposal,
                id,
                UUID.randomUUID().toString(),
                "AGENT",
                null,
                null,
                1,
                1,
                "VALIDATED",
                2599L,
                null,
                "{}",
                "a".repeat(64),
                Instant.now());
        String authorization = UUID.randomUUID().toString();
        authorizations.insert(
                authorization,
                id,
                1,
                "PENDING_REVIEW",
                "REFUND",
                1,
                proposal,
                operation,
                "b".repeat(64),
                2599,
                1,
                "CNY",
                "v1",
                null,
                Instant.now(),
                Instant.now());
        authorizations.decide(authorization, 1, "APPROVED", "demo-reviewer", "REVIEWER", "模拟验收", Instant.now());
        jdbc.update("UPDATE case_authorization SET status='CONSUMED' WHERE authorization_id=?", authorization);
        cases.insertTimeline(
                id,
                UUID.randomUUID().toString(),
                1,
                "EXECUTION_UPDATED",
                "{\"outcome\":\"FAILED\",\"operation_id\":\"" + operation + "\"}",
                Instant.now(),
                1);
        var detail = json.readTree(read("/api/v1/customer/cases/" + id, own()));
        assertThat(detail.get("allowed_actions").size()).isZero();
        assertThat(detail.get("result").get("message").stringValue()).contains("执行失败");
        for (String route : new String[] {"evidence", "cancel"}) {
            var body = route.equals("evidence")
                    ? Map.of("text", "不能修改", "evidence_kind", "CUSTOMER_STATEMENT")
                    : Map.of("reason", "不能撤销");
            rest.post()
                    .uri("/api/v1/cases/" + id + "/" + route)
                    .header("Authorization", "Bearer " + own())
                    .contentType(MediaType.APPLICATION_JSON)
                    .body(body)
                    .exchange()
                    .expectStatus()
                    .isEqualTo(409);
        }
        jdbc.update("UPDATE aftersale_case SET status='WAITING_CUSTOMER' WHERE case_id=?", id);
        String q = UUID.randomUUID().toString();
        cases.insertTimeline(
                id,
                UUID.randomUUID().toString(),
                2,
                "QUESTION_REQUIRED",
                "{\"question_id\":\"" + q + "\",\"questions\":[{\"prompt\":\"补充说明\"}]}",
                Instant.now(),
                1);
        assertThat(json.readTree(read("/api/v1/customer/cases/" + id, own()))
                        .get("allowed_actions")
                        .size())
                .isZero();
        rest.post()
                .uri("/api/v1/customer/cases/" + id + "/answers")
                .header("Authorization", "Bearer " + own())
                .header("If-Match", "\"1\"")
                .contentType(MediaType.APPLICATION_JSON)
                .body(Map.of("question_id", q, "text", "不能回答"))
                .exchange()
                .expectStatus()
                .isEqualTo(409);
        assertThat(jdbc.queryForObject("SELECT input_revision FROM aftersale_case WHERE case_id=?", Integer.class, id))
                .isEqualTo(1);
    }

    @Test
    void questionDeadlineIsCappedByThePersistedCaseExpiry() {
        String id = row("M-1001", "C-2002", "WAITING_CUSTOMER", Instant.now());
        Instant expiry = Instant.now().minusSeconds(1);
        jdbc.update("UPDATE aftersale_case SET expires_at=? WHERE case_id=?", java.sql.Timestamp.from(expiry), id);
        String q = UUID.randomUUID().toString();
        cases.insertTimeline(
                id,
                UUID.randomUUID().toString(),
                1,
                "QUESTION_REQUIRED",
                "{\"question_id\":\"" + q + "\",\"questions\":[{\"prompt\":\"最近发出但工单已到期\"}]}",
                Instant.now(),
                1);
        var detail = json.readTree(read("/api/v1/customer/cases/" + id, own()));
        assertThat(detail.get("questions").get(0).get("status").stringValue()).isEqualTo("EXPIRED");
        assertThat(Instant.parse(
                        detail.get("questions").get(0).get("expires_at").stringValue()))
                .isBefore(Instant.now());
        rest.post()
                .uri("/api/v1/customer/cases/" + id + "/answers")
                .header("Authorization", "Bearer " + own())
                .header("If-Match", "\"1\"")
                .contentType(MediaType.APPLICATION_JSON)
                .body(Map.of("question_id", q, "text", "不能延长期限"))
                .exchange()
                .expectStatus()
                .isEqualTo(409);
    }
}
