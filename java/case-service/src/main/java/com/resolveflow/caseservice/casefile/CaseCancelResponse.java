package com.resolveflow.caseservice.casefile;

import com.fasterxml.jackson.annotation.JsonInclude;
import com.fasterxml.jackson.annotation.JsonProperty;

/** The 200 body of a cancel, member for member with {@code CaseCancelResponse}. */
@JsonInclude(JsonInclude.Include.NON_NULL)
public record CaseCancelResponse(@JsonProperty("case_id") String caseId, CaseStatus status, long version) {}
