package com.resolveflow.caseservice.casefile;

import com.fasterxml.jackson.annotation.JsonInclude;
import com.fasterxml.jackson.annotation.JsonProperty;

/**
 * The 200 body of an append, member for member with {@code EvidenceSubmissionResponse}.
 *
 * <p>{@code revoked_authorization_id} is absent when the case had no live authorisation to retire, which is
 * the ordinary answer: most material arrives before any run proposed anything. The member is omitted rather
 * than sent as null, matching the contract's schema (a null branch exists for readers that always render the
 * member) — a writer that always sent null would make "nothing was retired" and "a reader that never looked"
 * the same bytes.
 */
@JsonInclude(JsonInclude.Include.NON_NULL)
public record EvidenceSubmissionResponse(
        @JsonProperty("case_id") String caseId,
        @JsonProperty("input_revision") int inputRevision,
        long version,
        @JsonProperty("revoked_authorization_id") String revokedAuthorizationId) {}
