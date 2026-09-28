package com.resolveflow.caseservice.casefile;

import com.fasterxml.jackson.annotation.JsonInclude;
import com.fasterxml.jackson.annotation.JsonProperty;
import java.time.Instant;
import java.util.List;
import tools.jackson.databind.JsonNode;

/**
 * The case view (docs/core-contracts.md:29), member for member with the contract's
 * {@code CaseSnapshot}.
 *
 * <p>{@code proposal} is carried as the JSON that was submitted plus the members this service decided, rather
 * than as a record mirroring every proposal member: the contract says an absent amount is not a null one, so
 * rebuilding the document from a parsed record would turn "nothing was suggested" into an explicit null. The
 * operation member is still absent until the step that creates it exists — absent, not null, because an empty
 * member and a missing member would be two spellings of the same fact.
 *
 * <p>{@code authorization} is the human decision's subject (C03.3a): which payment a reviewer is being asked
 * to approve, at which revision, with the operation id and payload hash fixed at creation.
 *
 * <p>{@code evidence} is the material itself, because a reviewer cannot verify what it cannot read: the case
 * view is the human surface for the same records the internal route serves as citations
 * (docs/core-contracts.md:35, added in C03.2c).
 */
@JsonInclude(JsonInclude.Include.NON_NULL)
public record CaseSnapshotResponse(
        @JsonProperty("case") CaseSummaryResponse caseSummary,
        JsonNode proposal,
        AuthorizationStateResponse authorization,
        List<EvidenceViewResponse> evidence,
        List<TimelineEventView> timeline) {

    /** The case itself: the members the contract requires of a {@code CaseSummary}. */
    @JsonInclude(JsonInclude.Include.NON_NULL)
    public record CaseSummaryResponse(
            @JsonProperty("case_id") String caseId,
            CaseStatus status,
            @JsonProperty("input_revision") int inputRevision,
            long version,
            @JsonProperty("created_at") Instant createdAt,
            @JsonProperty("updated_at") Instant updatedAt,
            @JsonProperty("requested_actions") List<RequestedAction> requestedActions,
            @JsonProperty("line_id") String lineId,
            @JsonProperty("order_id") String orderId,
            String description) {}

    /**
     * One piece of material as the case view serves it: where it came from, what it says, and — for a human
     * verification — which record it is about and what the reviewer concluded.
     *
     * <p>{@code observationId} is the record's own id, which is the value a verification cites as {@code
     * source_evidence_id}: the round trip a reviewer actually performs is "read the material, name it,
     * record what I found", and it should not need a second identifier that appears nowhere else.
     */
    @JsonInclude(JsonInclude.Include.NON_NULL)
    public record EvidenceViewResponse(
            @JsonProperty("observation_id") String observationId,
            @JsonProperty("source_ref") String sourceRef,
            @JsonProperty("source_version") String sourceVersion,
            @JsonProperty("content_hash") String contentHash,
            @JsonProperty("evidence_kind") EvidenceSourceType evidenceKind,
            @JsonProperty("content") String content,
            @JsonProperty("input_revision") int inputRevision,
            @JsonProperty("observed_at") Instant observedAt,
            @JsonProperty("appended_by") String appendedBy,
            @JsonProperty("appended_role") String appendedRole,
            @JsonProperty("reviewed_evidence_id") String reviewedEvidenceId,
            @JsonProperty("verification_result") VerificationResult verificationResult) {

        static EvidenceViewResponse of(EvidenceRepository.EvidenceRow row) {
            return new EvidenceViewResponse(
                    row.evidenceId(),
                    row.sourceRef(),
                    row.sourceVersion(),
                    row.contentHash(),
                    row.kind(),
                    row.content(),
                    row.inputRevision(),
                    row.observedAt(),
                    row.appendedBy(),
                    row.appendedRole(),
                    row.reviewedEvidenceId(),
                    row.conclusion());
        }
    }
}
