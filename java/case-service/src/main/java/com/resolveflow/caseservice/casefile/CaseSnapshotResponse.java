package com.resolveflow.caseservice.casefile;

import com.fasterxml.jackson.annotation.JsonInclude;
import com.fasterxml.jackson.annotation.JsonProperty;
import java.time.Instant;
import java.util.List;

/**
 * The case view (docs/core-contracts.md:29), member for member with the contract's
 * {@code CaseSnapshot}.
 *
 * <p>The proposal, authorisation and operation members are absent until the steps that create them
 * exist. Absent, not null: an empty member and a missing member would be two spellings of the same
 * fact, and the project keeps one (the same rule that keeps {@code suggested_amount_minor} out of a
 * proposal that has no amount).
 */
@JsonInclude(JsonInclude.Include.NON_NULL)
public record CaseSnapshotResponse(
        @JsonProperty("case") CaseSummaryResponse caseSummary,
        List<EvidenceRefResponse> evidence,
        List<TimelineEventResponse> timeline) {

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
            @JsonProperty("line_id") String lineId) {}

    /** Where a fact came from; the traceable half of "原文与模型推断分开" (docs/agent-spec.md). */
    @JsonInclude(JsonInclude.Include.NON_NULL)
    public record EvidenceRefResponse(
            @JsonProperty("observation_id") String observationId,
            @JsonProperty("source_ref") String sourceRef,
            @JsonProperty("source_version") String sourceVersion,
            @JsonProperty("content_hash") String contentHash) {}

    @JsonInclude(JsonInclude.Include.NON_NULL)
    public record TimelineEventResponse(
            @JsonProperty("event_id") String eventId,
            TimelineEventType type,
            @JsonProperty("occurred_at") Instant occurredAt,
            String summary,
            Integer revision) {}
}
