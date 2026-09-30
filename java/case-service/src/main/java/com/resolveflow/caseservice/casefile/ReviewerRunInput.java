package com.resolveflow.caseservice.casefile;

import java.util.Comparator;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import tools.jackson.databind.ObjectMapper;

/** Case-owned, append-only inputs at the dispatched revision. No model inference is projected here. */
final class ReviewerRunInput {
    private static final ObjectMapper MAPPER = new ObjectMapper();

    private ReviewerRunInput() {}

    static Map<String, Object> snapshot(
            CaseRepository cases, EvidenceRepository evidence, String caseId, int revision) {
        List<Map<String, Object>> materials = evidence.findRecent(caseId, CaseEvidenceService.MAX_RECORDS).stream()
                .filter(row -> row.inputRevision() <= revision)
                .sorted(Comparator.comparingInt(EvidenceRepository.EvidenceRow::inputRevision)
                        .thenComparing(EvidenceRepository.EvidenceRow::evidenceId))
                .map(ReviewerRunInput::material)
                .toList();
        List<Map<String, Object>> questions = cases.findTimeline(caseId).stream()
                .filter(event -> event.kind() == TimelineEventType.QUESTION_REQUIRED
                        && event.inputRevision() <= revision)
                .map(event -> {
                    var detail = MAPPER.readTree(event.detail());
                    Map<String, Object> question = new LinkedHashMap<>();
                    question.put("question_id", detail.get("question_id").stringValue());
                    question.put("input_revision", event.inputRevision());
                    question.put("questions", MAPPER.convertValue(detail.get("questions"), List.class));
                    return question;
                })
                .toList();
        return materials.isEmpty() && questions.isEmpty()
                ? Map.of()
                : Map.of("materials", materials, "questions", questions);
    }

    private static Map<String, Object> material(EvidenceRepository.EvidenceRow row) {
        Map<String, Object> result = new LinkedHashMap<>();
        result.put("evidence_id", row.evidenceId());
        result.put("source_type", row.sourceType());
        result.put("source_ref", row.sourceRef());
        result.put("source_version", row.sourceVersion());
        result.put("content_hash", row.contentHash());
        result.put("input_revision", row.inputRevision());
        result.put("content", row.content() == null ? "" : row.content());
        if (row.questionId() != null) result.put("question_id", row.questionId());
        if (row.reviewedEvidenceId() != null) result.put("reviewed_evidence_id", row.reviewedEvidenceId());
        if (row.verificationResult() != null) result.put("verification_result", row.verificationResult());
        return result;
    }
}
