package com.resolveflow.caseservice.support;

import static org.assertj.core.api.Assertions.*;
import static org.mockito.ArgumentMatchers.*;
import static org.mockito.Mockito.*;

import com.resolveflow.caseservice.order.CommerceOrderLineClient;
import java.time.Instant;
import java.util.Map;
import java.util.Optional;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.context.annotation.Import;
import tools.jackson.databind.JsonNode;

/** Reuses the consultation HTTP fixture; inherited tests also protect its existing behavior. */
@Import(SupportApiTest.Configuration.class)
class SupportRefundApiTest extends SupportApiTest {
    @org.springframework.beans.factory.annotation.Autowired
    SupportRefundService refunds;

    @org.springframework.beans.factory.annotation.Autowired
    com.resolveflow.caseservice.casefile.CaseRepository cases;

    @Test
    void assistantOrderFactsReadCurrentRefundApplicationWithoutLeakingInvestigation() {
        var c = open("support-A");
        var created = confirmDraft(c, prepareDraft(c, "facts-draft"), "facts-confirm", 200);
        String caseId = created.path("application").path("case").path("case_id").asString();
        var current = message(get(path(c), buyer, 200), "facts-question", "退款到哪里了？", "ASSISTANT");
        when(assistant.execute(anyString(), any())).thenAnswer(i -> {
            Map<String, Object> request = i.getArgument(1);
            String route = "/internal/v1/support/turns/" + request.get("run_id") + "/facts/order";
            String credential = "Bearer " + request.get("tool_token");
            String previousVersion = null;
            for (String status : java.util.List.of("QUEUED", "AUTHORIZED", "RECONCILING", "CLOSED_SUCCESS")) {
                jdbc.update("UPDATE aftersale_case SET status=?,version=version+1 WHERE case_id=?", status, caseId);
                var fact = json.readTree(rest.get()
                        .uri(route)
                        .header("Authorization", credential)
                        .exchange()
                        .expectStatus()
                        .isOk()
                        .expectBody(String.class)
                        .returnResult()
                        .getResponseBody());
                var application = fact.path("refund_application");
                assertThat(application.path("present").asBoolean()).isTrue();
                assertThat(application.path("case_id").asString()).isEqualTo(caseId);
                assertThat(application.path("line_id").asString()).isEqualTo("support-A");
                assertThat(application.path("status").asString()).isEqualTo(status);
                assertThat(application.path("message").asString()).isNotBlank();
                assertThat(application.path("amount_minor").isNull())
                        .isTrue(); // No authorization: never invent an amount.
                assertThat(application.toString())
                        .doesNotContain("proposal", "policy_refs", "evidence_refs", "materials");
                assertThat(fact.path("version").asString()).isNotEqualTo(previousVersion);
                previousVersion = fact.path("version").asString();
            }
            return json.readTree("{\"status\":\"FAILED\",\"reason\":\"TEST_COMPLETE\"}");
        });
        turns.dispatchOne();
        assertThat(get(path(current), buyer, 200).path("messages").size()).isEqualTo(1);
    }

    @Test
    void assistantOrderFactsDoNotEquateMissingInquiryTicketWithMissingRefundApplication() {
        cases.insertCase(
                java.util.UUID.randomUUID().toString(),
                "M-1002",
                "C-foreign",
                java.util.UUID.randomUUID().toString(),
                "support-A",
                "foreign private refund",
                "CLOSED_SUCCESS",
                1,
                1,
                null,
                Instant.now(),
                Instant.now());
        var c = message(open("support-A"), "facts-none-question", "有退款申请吗？", "ASSISTANT");
        when(assistant.execute(anyString(), any())).thenAnswer(i -> {
            Map<String, Object> request = i.getArgument(1);
            var fact = json.readTree(rest.get()
                    .uri("/internal/v1/support/turns/" + request.get("run_id") + "/facts/order")
                    .header("Authorization", "Bearer " + request.get("tool_token"))
                    .exchange()
                    .expectStatus()
                    .isOk()
                    .expectBody(String.class)
                    .returnResult()
                    .getResponseBody());
            assertThat(fact.path("refund_application").path("present").asBoolean())
                    .isFalse();
            assertThat(fact.path("refund_application").path("status").asString())
                    .isEqualTo("NONE");
            return json.readTree("{\"status\":\"FAILED\",\"reason\":\"TEST_COMPLETE\"}");
        });
        turns.dispatchOne();
    }

    @Test
    void publishedSummaryIsPrivateAndDoesNotCreateApplicationOrDraft() {
        var c = message(open("support-A"), "summary-question", "请整理退款申请原因", "ASSISTANT");
        when(assistant.execute(anyString(), any())).thenAnswer(i -> {
            Map<String, Object> request = i.getArgument(1);
            return json.valueToTree(Map.of(
                    "run_id",
                    request.get("run_id"),
                    "conversation_id",
                    request.get("conversation_id"),
                    "input_version",
                    request.get("input_version"),
                    "status",
                    "SUCCEEDED",
                    "mode",
                    "mock",
                    "answer",
                    Map.of(
                            "text",
                            "可核对申请摘要后确认。",
                            "citations",
                            java.util.List.of(),
                            "refund_summary",
                            "客户反馈未收到商品，希望核实签收后退款。")));
        });
        turns.dispatchOne();
        var current = get(path(c), buyer, 200);
        assertThat(current.path("messages")
                        .get(1)
                        .path("assistant")
                        .path("refund_summary")
                        .asString())
                .contains("客户反馈");
        assertThat(jdbc.queryForObject("SELECT COUNT(*) FROM aftersale_case", Integer.class))
                .isZero();
        assertThat(jdbc.queryForObject("SELECT COUNT(*) FROM support_refund_draft", Integer.class))
                .isZero();
        get(path(c), merchant, 403);
        get(path(c) + "/refund-application", otherBuyer, 404);
        var shared = post(
                path(c) + "/tickets",
                buyer,
                "share-without-refund-summary",
                Map.of(
                        "expected_version",
                        current.path("version").asLong(),
                        "summary",
                        "请核查签收情况",
                        "shared_message_ids",
                        java.util.List.of(),
                        "assistant_message_id",
                        current.path("messages").get(1).path("message_id").asString()),
                200);
        var ticket = get("/tickets/" + shared.path("ticket").path("ticket_id").asString(), merchant, 200);
        assertThat(ticket.path("ticket").path("report").has("refund_summary")).isFalse();
        assertThat(jdbc.queryForObject("SELECT COUNT(*) FROM aftersale_case", Integer.class))
                .isZero();
    }

    @Test
    void blankRefundSummaryCannotBePublishedAsAnActionableOffer() {
        var c = message(open("support-A"), "blank-summary-question", "请整理退款申请原因", "ASSISTANT");
        when(assistant.execute(anyString(), any())).thenAnswer(i -> {
            Map<String, Object> request = i.getArgument(1);
            return json.valueToTree(Map.of(
                    "run_id",
                    request.get("run_id"),
                    "conversation_id",
                    request.get("conversation_id"),
                    "input_version",
                    request.get("input_version"),
                    "status",
                    "SUCCEEDED",
                    "mode",
                    "mock",
                    "answer",
                    Map.of("text", "可核对申请摘要后确认。", "citations", java.util.List.of(), "refund_summary", " ")));
        });
        turns.dispatchOne();
        assertThat(get(path(c), buyer, 200).path("messages").size()).isEqualTo(1);
        assertThat(jdbc.queryForObject("SELECT COUNT(*) FROM aftersale_case", Integer.class))
                .isZero();
    }

    @BeforeEach
    void refundFacts() {
        deleteAllCaseData(jdbc);
        when(commerce.readLineContext(anyString()))
                .thenAnswer(i -> Optional.of(new CommerceOrderLineClient.LineContext(
                        "order-" + i.getArgument(0),
                        i.getArgument(0),
                        "M-1001",
                        "C-B3001-M1001",
                        "SKU",
                        "electronics",
                        1,
                        32900,
                        0,
                        0,
                        "CNY",
                        Instant.parse("2026-09-20T08:00:00Z"),
                        "PAID",
                        1)));
    }

    JsonNode confirmDraft(JsonNode c, JsonNode v, String key, int status) {
        return post(
                path(c) + "/refund-drafts/" + v.path("draft").path("draft_id").asString() + "/confirm",
                buyer,
                key,
                Map.of(
                        "revision",
                        v.path("draft").path("revision").asLong(),
                        "expected_version",
                        c.path("version").asLong()),
                status);
    }

    @Test
    void concurrentSameRequestCreatesOnlyOneCaseAndExistingEntryIsRecovered() throws Exception {
        var c = open("support-A");
        var v = prepareDraft(c, "concurrent-draft");
        var session = principals.session(buyer);
        var body = new com.resolveflow.shared.support.SupportRefundWire.Confirm(1L, 1L);
        String id = c.path("conversation_id").asString(),
                d = v.path("draft").path("draft_id").asString();
        try (var pool = java.util.concurrent.Executors.newFixedThreadPool(2)) {
            var first = pool.submit(() -> refunds.confirm(session, id, d, "concurrent-confirm", body));
            var second = pool.submit(() -> refunds.confirm(session, id, d, "concurrent-confirm", body));
            assertThat(first.get(15, java.util.concurrent.TimeUnit.SECONDS))
                    .isEqualTo(second.get(15, java.util.concurrent.TimeUnit.SECONDS));
        }
        assertThat(jdbc.queryForObject("SELECT COUNT(*) FROM aftersale_case", Integer.class))
                .isEqualTo(1);
        var existing = prepareDraft(c, "existing-prepare");
        assertThat(existing.path("application").path("case").path("case_id").asString())
                .isNotBlank();
    }

    @Test
    void oldApplicationEntryAndUnknownProgressDoNotCreateAnotherCaseOrLeakChat() {
        var c = open("support-A");
        var v = prepareDraft(c, "old-entry-prepare");
        var original = postRaw(
                "/api/v1/cases",
                buyer,
                "old-entry",
                Map.of(
                        "line_id",
                        "support-A",
                        "description",
                        "客户在原页面提交的原因",
                        "requested_actions",
                        java.util.List.of("REFUND")),
                201);
        var got = confirmDraft(c, v, "old-entry-confirm", 200);
        assertThat(got.path("application").path("case").path("case_id").asString())
                .isEqualTo(original.path("case_id").asString());
        jdbc.update(
                "UPDATE aftersale_case SET status='RECONCILING' WHERE case_id=?",
                original.path("case_id").asString());
        var progress = get(path(c) + "/refund-application", buyer, 200);
        assertThat(progress.path("application").path("case").path("status").asString())
                .isEqualTo("RECONCILING");
        assertThat(progress.path("application").has("authorization")).isFalse();
        assertThat(jdbc.queryForObject("SELECT COUNT(*) FROM aftersale_case", Integer.class))
                .isEqualTo(1);
        verifyNoInteractions(assistant);
    }

    @Test
    void confirmCreatesOneCaseAndResponseLossReplaysTheOriginalReceipt() {
        var c = open("support-A");
        var v = prepareDraft(c, "confirm-prepare");
        var created = confirmDraft(c, v, "confirm-once", 200);
        String caseId = created.path("application").path("case").path("case_id").asString();
        assertThat(caseId).isNotBlank();
        assertThat(created.path("draft").path("status").asString()).isEqualTo("CONFIRMED");
        assertThat(created.path("draft").path("case_id").asString()).isEqualTo(caseId);
        assertThat(jdbc.queryForObject("SELECT description FROM aftersale_case WHERE case_id=?", String.class, caseId))
                .isEqualTo(v.path("draft").path("reason").asString());
        message(c, "after-confirm-message", "继续问一下进度", "ASSISTANT");
        assertThat(confirmDraft(c, v, "confirm-once", 200)).isEqualTo(created);
        assertThat(confirmDraft(c, v, "confirm-another-key", 200)
                        .path("application")
                        .path("case")
                        .path("case_id")
                        .asString())
                .isEqualTo(caseId);
        assertThat(jdbc.queryForObject("SELECT COUNT(*) FROM aftersale_case", Integer.class))
                .isEqualTo(1);
        assertThat(jdbc.queryForObject("SELECT COUNT(*) FROM agent_binding", Integer.class))
                .isEqualTo(1);
        assertThat(jdbc.queryForObject("SELECT COUNT(*) FROM case_evidence WHERE case_id=?", Integer.class, caseId))
                .isEqualTo(1);
        post(
                path(c) + "/refund-drafts/" + v.path("draft").path("draft_id").asString() + "/confirm",
                buyer,
                "confirm-once",
                Map.of("revision", 99, "expected_version", 1),
                409);
        verifyNoInteractions(assistant);
    }

    @Test
    void onlyFinalConfirmedReasonBecomesAnUnverifiedInitialCustomerStatement() {
        var c = message(open("support-A"), "private-question", "私有咨询原文不应共享", "ASSISTANT");
        var v = prepareDraft(c, "statement-draft");
        String draftId = v.path("draft").path("draft_id").asString();
        String reason = "本人未收到商品，请商家核实后处理整件退款。";
        var edited = post(
                path(c) + "/refund-drafts/" + draftId + "/edit",
                buyer,
                "statement-edit",
                Map.of("revision", 1, "reason", reason),
                200);
        assertThat(jdbc.queryForObject("SELECT COUNT(*) FROM case_evidence", Integer.class))
                .isZero();
        var created = confirmDraft(c, edited, "statement-confirm", 200);
        String caseId = created.path("application").path("case").path("case_id").asString();
        var claims = jdbc.queryForList("SELECT * FROM case_evidence WHERE case_id=?", caseId);
        assertThat(claims).hasSize(1);
        var claim = claims.getFirst();
        assertThat(claim.get("source_type")).isEqualTo("CUSTOMER_STATEMENT");
        assertThat(claim.get("content")).isEqualTo(reason);
        assertThat(claim.get("source_ref").toString())
                .contains(c.path("conversation_id").asString(), draftId);
        assertThat(claim.get("source_version")).isEqualTo("conversation-2:draft-2");
        assertThat(claim.get("content_hash").toString()).matches("[0-9a-f]{64}");
        assertThat(claim.get("appended_role")).isEqualTo("CUSTOMER");
        assertThat(claim.get("appended_by")).isNotNull();
        assertThat(claim.get("input_revision")).isEqualTo(1);
        assertThat(claim.get("verification_result")).isNull();
        assertThat(claim.get("reviewed_evidence_id")).isNull();
        assertThatThrownBy(() -> jdbc.update(
                        "UPDATE case_evidence SET source_type='REVIEWER_VERIFICATION',appended_role='REVIEWER' WHERE case_id=?",
                        caseId))
                .isInstanceOf(org.springframework.dao.DataAccessException.class)
                .hasRootCauseMessage("Check constraint 'chk_evidence_revision' is violated.");
        assertThat(jdbc.queryForObject(
                        "SELECT input_revision FROM aftersale_case WHERE case_id=?", Integer.class, caseId))
                .isEqualTo(1);
        assertThat(jdbc.queryForObject("SELECT COUNT(*) FROM agent_binding WHERE case_id=?", Integer.class, caseId))
                .isEqualTo(1);
        assertThat(confirmDraft(c, edited, "statement-confirm", 200)).isEqualTo(created);
        assertThat(jdbc.queryForObject("SELECT COUNT(*) FROM case_evidence WHERE case_id=?", Integer.class, caseId))
                .isEqualTo(1);
    }

    @Test
    void initialStatementFailureRollsBackCaseBindingDraftAndReceipts() {
        var c = open("support-A");
        var v = prepareDraft(c, "statement-rollback-draft");
        jdbc.execute(
                "ALTER TABLE case_evidence ADD CONSTRAINT reject_initial_statement CHECK(source_type<>'CUSTOMER_STATEMENT')");
        try {
            confirmDraft(c, v, "statement-rollback-confirm", 500);
        } finally {
            jdbc.execute("ALTER TABLE case_evidence DROP CHECK reject_initial_statement");
        }
        for (String table :
                java.util.List.of("aftersale_case", "agent_binding", "case_evidence", "request_idempotency")) {
            assertThat(jdbc.queryForObject("SELECT COUNT(*) FROM " + table, Integer.class))
                    .isZero();
        }
        assertThat(get(path(c) + "/refund-application", buyer, 200)
                        .path("draft")
                        .path("status")
                        .asString())
                .isEqualTo("DRAFT");
        confirmDraft(c, v, "statement-rollback-confirm", 200);
        assertThat(jdbc.queryForObject("SELECT COUNT(*) FROM case_evidence", Integer.class))
                .isEqualTo(1);
    }

    @org.junit.jupiter.params.ParameterizedTest
    @org.junit.jupiter.params.provider.ValueSource(strings = {"CONFIRMED", "REFUTED", "INCONCLUSIVE"})
    void merchantCanVerifyTheConfirmedReasonAndDispatchANewRevision(String result) {
        var c = open("support-A");
        var draft = prepareDraft(c, "reviewable-reason-draft");
        var created = confirmDraft(c, draft, "reviewable-reason-confirm", 200);
        String caseId = created.path("application").path("case").path("case_id").asString();
        var initial = jdbc.queryForMap("SELECT * FROM case_evidence WHERE case_id=?", caseId);
        // This inherited fixture retains the legacy multi-staff shop; claim through its real route.
        claimTestCase(caseId, "demo-admin");
        String text = rest.post()
                .uri("/api/v1/cases/" + caseId + "/reviewed-evidence")
                .header("Authorization", merchant)
                .headers(h -> addReviewHeaders(h, caseId))
                .contentType(org.springframework.http.MediaType.APPLICATION_JSON)
                .body(Map.of(
                        "source_evidence_id",
                        initial.get("evidence_id"),
                        "verification_result",
                        result,
                        "reason",
                        "商家核对订单及承运记录后登记核验结论"))
                .exchange()
                .expectStatus()
                .isOk()
                .expectBody(String.class)
                .returnResult()
                .getResponseBody();
        assertThat(json.readTree(text).path("input_revision").asInt()).isEqualTo(2);
        assertThat(jdbc.queryForObject("SELECT COUNT(*) FROM agent_binding WHERE case_id=?", Integer.class, caseId))
                .isEqualTo(2);
        assertThat(jdbc.queryForMap("SELECT * FROM case_evidence WHERE case_id=? AND input_revision=1", caseId))
                .isEqualTo(initial);
        var check = jdbc.queryForMap("SELECT * FROM case_evidence WHERE case_id=? AND input_revision=2", caseId);
        assertThat(check.get("reviewed_evidence_id")).isEqualTo(initial.get("evidence_id"));
        assertThat(check.get("verification_result")).isEqualTo(result);
        verifyNoInteractions(assistant);
    }

    @Test
    void staleExpiredAndChangedAmountCannotBeConfirmed() {
        var c = open("support-A");
        var v = prepareDraft(c, "stale-prepare");
        message(c, "correction-before-confirm", "不要退款了", "ASSISTANT");
        confirmDraft(c, v, "stale-confirm", 409);
        var updated = get(path(c), buyer, 200);
        var newer = prepareDraft(updated, "newer-prepare");
        jdbc.update(
                "UPDATE support_refund_draft SET expires_at=TIMESTAMP('2020-01-01') WHERE conversation_id=?",
                c.path("conversation_id").asString());
        confirmDraft(updated, newer, "expired-confirm", 409);
        var last = prepareDraft(updated, "amount-prepare");
        jdbc.update(
                "UPDATE support_refund_draft SET amount_minor=1 WHERE conversation_id=?",
                c.path("conversation_id").asString());
        confirmDraft(updated, last, "amount-confirm", 409);
        assertThat(jdbc.queryForObject("SELECT COUNT(*) FROM aftersale_case", Integer.class))
                .isZero();
    }

    @Test
    void caseAndLinkRollbackTogetherWhenConfirmationWriteFails() {
        var c = open("support-A");
        var v = prepareDraft(c, "rollback-prepare");
        jdbc.execute(
                "ALTER TABLE support_refund_draft ADD CONSTRAINT reject_refund_confirmation CHECK(status<>'CONFIRMED')");
        try {
            confirmDraft(c, v, "rollback-confirm", 500);
        } finally {
            jdbc.execute("ALTER TABLE support_refund_draft DROP CHECK reject_refund_confirmation");
        }
        assertThat(jdbc.queryForObject("SELECT COUNT(*) FROM aftersale_case", Integer.class))
                .isZero();
        assertThat(jdbc.queryForObject("SELECT COUNT(*) FROM agent_binding", Integer.class))
                .isZero();
        assertThat(jdbc.queryForObject("SELECT COUNT(*) FROM case_evidence", Integer.class))
                .isZero();
        assertThat(jdbc.queryForObject("SELECT COUNT(*) FROM request_idempotency", Integer.class))
                .isZero();
        assertThat(get(path(c) + "/refund-application", buyer, 200)
                        .path("draft")
                        .path("status")
                        .asString())
                .isEqualTo("DRAFT");
        assertThat(confirmDraft(c, v, "rollback-confirm", 200)
                        .path("application")
                        .isObject())
                .isTrue();
    }

    JsonNode prepareDraft(JsonNode c, String key) {
        return post(
                path(c) + "/refund-drafts",
                buyer,
                key,
                Map.of("expected_version", c.path("version").asLong(), "reason", "未收到商品，希望核查后退款。"),
                200);
    }

    @Test
    void draftOnlyIsPersistentPrivateAndUsesOrderMoney() {
        var c = open("support-A");
        int before = jdbc.queryForObject("SELECT COUNT(*) FROM aftersale_case", Integer.class);
        var v = prepareDraft(c, "refund-draft");
        assertThat(v.path("draft").path("amount_minor").asLong()).isEqualTo(32900);
        assertThat(v.path("draft").path("revision").asLong()).isEqualTo(1);
        assertThat(get(path(c) + "/refund-application", buyer, 200)).isEqualTo(v);
        assertThat(prepareDraft(c, "refund-draft")).isEqualTo(v);
        get(path(c) + "/refund-application", otherBuyer, 404);
        get(path(c) + "/refund-application", merchant, 403);
        assertThat(jdbc.queryForObject("SELECT COUNT(*) FROM aftersale_case", Integer.class))
                .isEqualTo(before);
        verifyNoInteractions(assistant);
    }

    @Test
    void editCancelAndNewInputDoNotSubmitAnything() {
        var c = open("support-A");
        var v = prepareDraft(c, "draft-edit");
        String d = v.path("draft").path("draft_id").asString();
        var edited = post(
                path(c) + "/refund-drafts/" + d + "/edit",
                buyer,
                "edit-reason",
                Map.of("revision", 1, "reason", "已联系家人确认未收到，希望退款。"),
                200);
        assertThat(edited.path("draft").path("revision").asInt()).isEqualTo(2);
        // Another tab preparing the same accepted answer must not overwrite an already edited reason.
        assertThat(prepareDraft(c, "second-tab-prepare").path("draft")).isEqualTo(edited.path("draft"));
        post(path(c) + "/refund-drafts/" + d + "/edit", buyer, "old-edit", Map.of("revision", 1, "reason", "旧原因"), 409);
        var cancelled =
                post(path(c) + "/refund-drafts/" + d + "/cancel", buyer, "cancel-draft", Map.of("revision", 2), 200);
        assertThat(cancelled.path("draft").path("status").asString()).isEqualTo("CANCELLED");
        assertThat(cancelled.path("draft").path("reason").asString()).contains("家人");
        var fresh = prepareDraft(c, "new-draft");
        message(c, "new-message", "刚刚找到包裹了，先不要退款", "ASSISTANT");
        assertThat(get(path(c) + "/refund-application", buyer, 200)
                        .path("draft")
                        .path("status")
                        .asString())
                .isEqualTo("STALE");
        assertThat(fresh.path("application").isNull()).isTrue();
        verifyNoInteractions(assistant);
    }

    @Test
    void expiredOrWrongVersionCannotBeEditedAndBodyReplayConflicts() {
        var c = open("support-A");
        var v = prepareDraft(c, "draft-expiry");
        String d = v.path("draft").path("draft_id").asString();
        post(path(c) + "/refund-drafts", buyer, "draft-expiry", Map.of("expected_version", 1, "reason", "不同原因"), 409);
        jdbc.update(
                "UPDATE support_refund_draft SET expires_at=TIMESTAMP('2020-01-01') WHERE conversation_id=?",
                c.path("conversation_id").asString());
        assertThat(get(path(c) + "/refund-application", buyer, 200)
                        .path("draft")
                        .path("status")
                        .asString())
                .isEqualTo("EXPIRED");
        post(
                path(c) + "/refund-drafts/" + d + "/edit",
                buyer,
                "expired-edit",
                Map.of("revision", 1, "reason", "原因"),
                409);
    }
}
