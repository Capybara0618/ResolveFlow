package com.resolveflow.caseservice.casefile;

import com.fasterxml.jackson.annotation.JsonInclude;
import com.fasterxml.jackson.annotation.JsonProperty;

/**
 * The answer to a recorded verification (contracts/core/openapi-case.yaml, {@code ReviewedEvidenceResponse}).
 *
 * <p>{@code revoked_authorization_id} names the live authorisation this new revision retired, and its
 * <b>absence</b> means there was no live authorisation to retire — not that nobody looked. The server always
 * looks (C03.3c, {@link LiveAuthorization}), because an authorisation is fixed to the revision its payload
 * was hashed from and this route moves that revision.
 *
 * <p>It is not conditional on the reviewer's verdict: a CONFIRMED verification retires the approval exactly
 * as a REFUTED one does. What invalidated the fixed payload is the input moving, and reporting a revocation
 * only for REFUTED would attribute it to the wrong fact.
 */
@JsonInclude(JsonInclude.Include.NON_NULL)
public record ReviewedEvidenceResponse(
        @JsonProperty("case_id") String caseId,
        @JsonProperty("evidence_id") String evidenceId,
        @JsonProperty("input_revision") int inputRevision,
        @JsonProperty("case_version") long caseVersion,
        @JsonProperty("revoked_authorization_id") String revokedAuthorizationId) {

    static ReviewedEvidenceResponse recorded(
            String caseId, String evidenceId, int inputRevision, long caseVersion, String revokedAuthorizationId) {
        return new ReviewedEvidenceResponse(caseId, evidenceId, inputRevision, caseVersion, revokedAuthorizationId);
    }
}
