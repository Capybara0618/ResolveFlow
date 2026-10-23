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
    @BeforeEach
    void refundFacts() {
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
