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
 * authorisation and operation members are still absent until the steps that create them exist — absent, not
 * null, because an empty member and a missing member would be two spellings of the same fact.
 */
@JsonInclude(JsonInclude.Include.NON_NULL)
public record CaseSnapshotResponse(
        @JsonProperty("case") CaseSummaryResponse caseSummary,
        JsonNode proposal,
        List<EvidenceRefResponse> evidence,
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
            @JsonProperty("line_id") String lineId) {}

    /** Where a fact came from; the traceable half of "原文与模型推断分开" (docs/agent-spec.md). */
    @JsonInclude(JsonInclude.Include.NON_NULL)
    public record EvidenceRefResponse(
            @JsonProperty("observation_id") String observationId,
            @JsonProperty("source_ref") String sourceRef,
            @JsonProperty("source_version") String sourceVersion,
            @JsonProperty("content_hash") String contentHash) {}
}
