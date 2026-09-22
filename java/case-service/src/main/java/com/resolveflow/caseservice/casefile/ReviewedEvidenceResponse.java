package com.resolveflow.caseservice.casefile;

import com.fasterxml.jackson.annotation.JsonInclude;
import com.fasterxml.jackson.annotation.JsonProperty;

/**
 * The answer to a recorded verification (contracts/core/openapi-case.yaml, {@code ReviewedEvidenceResponse}).
 *
 * <p>{@code revoked_authorization_id} is always absent today, and that absence has a meaning: no
 * authorisation was affected. There are no authorisations yet — the approval path is C03.3 — so a
 * verification that refutes a record cannot revoke anything, and this service does not pretend otherwise
 * by inventing an id. When C03.3 exists, a refutation of material an approved authorisation relied on will
 * fill this member instead of quietly leaving the authorisation in place.
 */
@JsonInclude(JsonInclude.Include.NON_NULL)
public record ReviewedEvidenceResponse(
        @JsonProperty("case_id") String caseId,
        @JsonProperty("evidence_id") String evidenceId,
        @JsonProperty("input_revision") int inputRevision,
        @JsonProperty("case_version") long caseVersion,
        @JsonProperty("revoked_authorization_id") String revokedAuthorizationId) {

    static ReviewedEvidenceResponse recorded(String caseId, String evidenceId, int inputRevision, long caseVersion) {
        return new ReviewedEvidenceResponse(caseId, evidenceId, inputRevision, caseVersion, null);
    }
}
