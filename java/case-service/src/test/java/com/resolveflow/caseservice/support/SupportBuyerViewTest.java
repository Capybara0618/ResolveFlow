package com.resolveflow.caseservice.support;

import static org.assertj.core.api.Assertions.*;

import org.junit.jupiter.api.Test;
import tools.jackson.databind.ObjectMapper;
import tools.jackson.databind.node.ObjectNode;

class SupportBuyerViewTest {
    final ObjectMapper json = new ObjectMapper();

    ObjectNode offer() {
        return (ObjectNode) json.readTree("""
                {"text":"商家还需要核实丢失情况。","refund_summary":"耳机没收到",
                 "buyer_view":{"version":"buyer-view-v1","parts":[
                   {"task_id":"refund","text":"商家还需要核实丢失情况。","action":"REFUND_APPLICATION"}]}}
                """);
    }

    @Test
    void structuredAndLegacyAnswersHaveNoAuthorityToCreateApplications() {
        assertThat(SupportBuyerView.valid(offer())).isTrue();
        assertThat(SupportBuyerView.valid(json.readTree("{\"text\":\"旧消息\"}"))).isTrue();
        var answer = offer();
        answer.remove("refund_summary");
        assertThat(SupportBuyerView.valid(answer)).isFalse();
    }

    @Test
    void rejectsInternalFieldsUnknownActionsAndHiddenReplacementText() {
        var answer = offer();
        var part = (ObjectNode) answer.path("buyer_view").path("parts").get(0);
        part.put("tool_name", "private-tool");
        assertThat(SupportBuyerView.valid(answer)).isFalse();
        part.remove("tool_name");
        part.put("action", "EXECUTE_REFUND");
        assertThat(SupportBuyerView.valid(answer)).isFalse();
        part.put("action", "REFUND_APPLICATION");
        part.put("text", "已经退款了");
        assertThat(SupportBuyerView.valid(answer)).isFalse();
    }

    @Test
    void rejectsDuplicateTasksMissingActionAndCompetingCardGuidance() {
        var answer = offer();
        var parts = (tools.jackson.databind.node.ArrayNode)
                answer.path("buyer_view").path("parts");
        var part = (ObjectNode) parts.get(0);
        part.put("guidance", "核对后提交");
        assertThat(SupportBuyerView.valid(answer)).isFalse();
        part.remove("guidance");
        parts.add(part.deepCopy());
        assertThat(SupportBuyerView.valid(answer)).isFalse();
        parts.remove(1);
        part.remove("action");
        assertThat(SupportBuyerView.valid(answer)).isFalse();
    }

    @Test
    void explicitGuideTextRemainsPartOfThePublishedMessage() {
        var answer = json.readTree("""
                {"text":"可以。\\n\\n先核对共享内容。","buyer_view":{"version":"buyer-view-v1","parts":[
                 {"task_id":"how","text":"可以。","guidance":"先核对共享内容。"}]}}
                """);
        assertThat(SupportBuyerView.valid(answer)).isTrue();
    }
}
