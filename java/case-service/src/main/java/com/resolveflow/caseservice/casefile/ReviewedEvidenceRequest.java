package com.resolveflow.caseservice.casefile;

import com.fasterxml.jackson.annotation.JsonProperty;

/**
 * {@code POST /api/v1/cases/{case_id}/reviewed-evidence} (docs/core-contracts.md:35).
 *
 * <p>Three required members: which record is being verified, what the reviewer concluded, and why. The
 * conclusion is bound as text and parsed in the service so an unknown value is the protocol's 422 with a
 * message naming the accepted ones, rather than a deserialisation failure that says nothing about which
 * member was wrong.
 */
public record ReviewedEvidenceRequest(
        @JsonProperty("source_evidence_id") String sourceEvidenceId,

        @JsonProperty("verification_result") String verificationResult,

        @JsonProperty("reason") String reason) {}
