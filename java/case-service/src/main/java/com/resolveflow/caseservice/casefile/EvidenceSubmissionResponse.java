package com.resolveflow.caseservice.casefile;

import com.fasterxml.jackson.annotation.JsonInclude;
import com.fasterxml.jackson.annotation.JsonProperty;

/** The 200 body of an append, member for member with {@code EvidenceSubmissionResponse}. */
@JsonInclude(JsonInclude.Include.NON_NULL)
public record EvidenceSubmissionResponse(
        @JsonProperty("case_id") String caseId,
        @JsonProperty("input_revision") int inputRevision,
        long version) {}
