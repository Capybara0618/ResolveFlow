package com.resolveflow.caseservice.casefile;

import java.util.List;

/**
 * The proposal a run submitted, member for member with the contract's {@code ProposalPayload}.
 *
 * <p>{@code caseType} and {@code recommendedAction} are bound as text and checked against the contract's
 * vocabulary rather than bound as enums: an unknown value is then a 422 that names it (structural refusal,
 * answered to the producer) instead of a deserialisation error the producer cannot read as a protocol answer.
 *
 * <p>Nothing here is trusted. {@code case_id}, {@code run_id} and {@code input_revision} are copies this
 * service cross-checks against the delivery it already verified (docs/core-contracts.md:58 keeps the compat
 * field structure; a copy to check is not a second truth), and the amounts and citations are re-checked
 * against this service's own records before anything is stored as valid.
 */
public record ProposalSubmission(
        @com.fasterxml.jackson.annotation.JsonProperty("schema_version")
        int schemaVersion,

        @com.fasterxml.jackson.annotation.JsonProperty("proposal_id")
        String proposalId,

        @com.fasterxml.jackson.annotation.JsonProperty("run_id")
        String runId,

        @com.fasterxml.jackson.annotation.JsonProperty("case_id")
        String caseId,

        @com.fasterxml.jackson.annotation.JsonProperty("input_revision")
        int inputRevision,

        @com.fasterxml.jackson.annotation.JsonProperty("case_type")
        String caseType,

        @com.fasterxml.jackson.annotation.JsonProperty("recommended_action")
        String recommendedAction,

        String summary,

        @com.fasterxml.jackson.annotation.JsonProperty("reason_codes")
        List<String> reasonCodes,

        @com.fasterxml.jackson.annotation.JsonProperty("suggested_amount_minor")
        Long suggestedAmountMinor,

        @com.fasterxml.jackson.annotation.JsonProperty("evidence_refs")
        List<EvidenceCitation> evidenceRefs,

        @com.fasterxml.jackson.annotation.JsonProperty("policy_refs")
        List<PolicyCitation> policyRefs,

        @com.fasterxml.jackson.annotation.JsonProperty("missing_evidence")
        List<String> missingEvidence) {

    /** The contract's protocol version for a proposal. */
    public static final int SCHEMA_VERSION = 2;

    /** At most this many citations of either kind, as the contract's arrays declare. */
    public static final int MAX_CITATIONS = 32;

    public boolean isRefund() {
        return "REFUND".equals(recommendedAction);
    }

    public List<PolicyCitation> policies() {
        return policyRefs == null ? List.of() : policyRefs;
    }

    public List<EvidenceCitation> evidence() {
        return evidenceRefs == null ? List.of() : evidenceRefs;
    }
}
