package com.resolveflow.caseservice.casefile;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.when;

import java.time.Instant;
import java.util.List;
import org.junit.jupiter.api.Test;
import tools.jackson.databind.ObjectMapper;

class ReviewerRunInputTest {
    @Test
    void snapshotKeepsQuestionAnswerAndHumanConclusionButExcludesFutureRevisions() {
        CaseRepository cases = mock(CaseRepository.class);
        EvidenceRepository evidence = mock(EvidenceRepository.class);
        Instant now = Instant.now();
        when(cases.findTimeline("case-a")).thenReturn(List.of(new TimelineEventRow(
                "case-a", "event-q", 1, TimelineEventType.QUESTION_REQUIRED,
                "{\"question_id\":\"q-carrier\",\"questions\":[{\"field\":\"carrier_statement\",\"prompt\":\"请提供承运商证明\"}]}",
                now, 1)));
        when(evidence.findRecent("case-a", 64)).thenReturn(List.of(
                material("ev-answer", 2, "CUSTOMER_STATEMENT", "q-carrier", null, null),
                material("ev-check", 3, "REVIEWER_VERIFICATION", null, "ev-answer", "CONFIRMED"),
                material("ev-future", 4, "CUSTOMER_STATEMENT", null, null, null)));

        var snapshot = new ObjectMapper().valueToTree(ReviewerRunInput.snapshot(cases, evidence, "case-a", 3));

        assertThat(snapshot.get("materials").size()).isEqualTo(2);
        assertThat(snapshot.get("materials").get(0).get("question_id").stringValue()).isEqualTo("q-carrier");
        assertThat(snapshot.get("materials").get(1).get("verification_result").stringValue()).isEqualTo("CONFIRMED");
        assertThat(snapshot.get("materials").get(1).get("content_hash").stringValue()).isEqualTo("a".repeat(64));
        assertThat(snapshot.get("questions").get(0).get("questions").get(0).get("prompt").stringValue())
                .isEqualTo("请提供承运商证明");
        assertThat(snapshot.toString()).doesNotContain("ev-future");
    }

    private static EvidenceRepository.EvidenceRow material(
            String id, int revision, String type, String question, String reviewed, String conclusion) {
        return new EvidenceRepository.EvidenceRow(
                "case-a", id, type, "case:" + id, Integer.toString(revision), "a".repeat(64),
                revision, Instant.now(), "原始材料", question, reviewed, conclusion, "reviewer", "REVIEWER", Instant.now());
    }
}
