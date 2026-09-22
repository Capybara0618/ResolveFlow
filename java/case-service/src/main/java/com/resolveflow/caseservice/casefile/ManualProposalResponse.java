package com.resolveflow.caseservice.casefile;

import com.fasterxml.jackson.annotation.JsonProperty;

/**
 * What the manual proposal route answers, member for member with the contract's
 * {@code ManualProposalResponse}.
 *
 * <p>Both versions are reported because both moved: the submission produced a new input revision and a new
 * case version, and those are what a reviewer's next request has to name ({@code If-Match} is the case
 * version, and the authorisation they will decide carries the revision).
 */
public record ManualProposalResponse(
        @JsonProperty("case_id") String caseId,
        @JsonProperty("proposal_id") String proposalId,
        @JsonProperty("input_revision") int inputRevision,
        @JsonProperty("case_version") long caseVersion) {}
