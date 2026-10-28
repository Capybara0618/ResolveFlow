package com.resolveflow.caseservice.support;

import static org.assertj.core.api.Assertions.*;
import static org.mockito.ArgumentMatchers.*;
import static org.mockito.Mockito.*;

import java.util.List;
import java.util.Map;
import org.junit.jupiter.api.Test;
import org.springframework.context.annotation.Import;

@Import(SupportApiTest.Configuration.class)
class SupportBuyerViewApiTest extends SupportApiTest {
    void response(boolean invalid) {
        when(assistant.execute(anyString(), any())).thenAnswer(i -> {
            Map<String, Object> request = i.getArgument(1);
            var part = new java.util.LinkedHashMap<String, Object>(
                    Map.of("task_id", "refund", "text", "商家还需要核实丢失情况。", "action", "REFUND_APPLICATION"));
            if (invalid) part.put("private_prompt", "must never be projected");
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
                            "商家还需要核实丢失情况。",
                            "citations",
                            List.of(),
                            "refund_summary",
                            "耳机没收到",
                            "buyer_view",
                            Map.of("version", "buyer-view-v1", "parts", List.of(part)))));
        });
    }

    @Test
    void presentationSurvivesPersistenceWithoutCreatingDraftOrLeakingToSharedReport() {
        var c = message(open("support-A"), "buyer-view", "耳机没收到，请准备退款原因", "ASSISTANT");
        response(false);
        turns.dispatchOne();
        var current = get(path(c), buyer, 200);
        var answer = current.path("messages").get(1).path("assistant");
        assertThat(answer.path("buyer_view").path("parts").get(0).path("action").asString())
                .isEqualTo("REFUND_APPLICATION");
        assertThat(count("support_refund_draft")).isZero();
        assertThat(count("aftersale_case")).isZero();
        get(path(c), merchant, 403);
        get(path(c), otherBuyer, 404);
        var shared = post(
                path(c) + "/tickets",
                buyer,
                "share-view",
                Map.of(
                        "expected_version",
                        current.path("version").asLong(),
                        "summary",
                        "只核查",
                        "shared_message_ids",
                        List.of(),
                        "assistant_message_id",
                        current.path("messages").get(1).path("message_id").asString()),
                200);
        var ticket = get("/tickets/" + shared.path("ticket").path("ticket_id").asString(), merchant, 200);
        assertThat(ticket.path("ticket").path("report").has("buyer_view")).isFalse();
        assertThat(ticket.path("ticket").path("report").has("refund_summary")).isFalse();
        assertThat(count("aftersale_case")).isZero();
    }

    @Test
    void invalidPresentationCannotPublishEvenWhenTheTopLevelAnswerLooksValid() {
        var c = message(open("support-A"), "invalid-view", "准备退款原因", "ASSISTANT");
        response(true);
        turns.dispatchOne();
        var current = get(path(c), buyer, 200);
        assertThat(current.path("assistant_turn").path("status").asString()).isEqualTo("FAILED");
        assertThat(current.path("messages").size()).isEqualTo(1);
        assertThat(count("support_refund_draft")).isZero();
    }
}
