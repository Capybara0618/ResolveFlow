package com.resolveflow.caseservice.casefile;

import com.fasterxml.jackson.annotation.JsonInclude;
import com.fasterxml.jackson.annotation.JsonProperty;

/** The 201 body, member for member with the contract's {@code CaseCreatedResponse}. */
@JsonInclude(JsonInclude.Include.NON_NULL)
public record CaseCreatedResponse(
        @JsonProperty("case_id") String caseId,
        CaseStatus status,
        @JsonProperty("input_revision") int inputRevision,
        long version) {}
