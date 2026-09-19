package com.resolveflow.shared.core;

import com.fasterxml.jackson.annotation.JsonInclude;
import com.fasterxml.jackson.annotation.JsonProperty;
import java.util.List;
import java.util.Map;

/**
 * Java records for the core-v1.2 wire objects.
 *
 * <p>The Python half is {@code resolveflow.contracts.core_models}; both are checked against {@code
 * contracts/core/*.schema.json} and against the same core fixture corpus. The names are deliberately
 * distinct from the v1 types (docs/core-contracts.md:71): nothing here aliases or extends a v1
 * record, no v1-only field is representable, and the records carry the protocol they belong to.
 *
 * <p>JSON is snake_case, so every component that is not already a single lowercase word carries
 * {@code @JsonProperty}. That asymmetry with the Python side is deliberate: the wire format is the
 * shared artefact, not either language's idiom.
 *
 * <p>Two members that a reader might expect and that are absent on purpose: a refund command has no
 * {@code schema_version} (every one of its fields is covered by {@code payload_hash}, and a field
 * outside the hash would let two different commands share a digest) and no {@code entitlement_id}
 * (docs/core-contracts.md:19). A result carries {@code aggregate_version} inside its payload rather
 * than on the envelope, because the version has exactly one home (docs/domain-model.md:3).
 */
public final class CoreContract {

    private CoreContract() {}

    /** The only executable core command (docs/core-contracts.md:65). */
    public record CoreRefundCommand(
            @JsonProperty("operation_id") String operationId,
            @JsonProperty("case_id") String caseId,
            @JsonProperty("authorization_id") String authorizationId,
            @JsonProperty("input_revision") long inputRevision,
            @JsonProperty("line_id") String lineId,
            @JsonProperty("merchant_id") String merchantId,
            String action,
            int quantity,
            String currency,
            @JsonProperty("amount_minor") long amountMinor,
            @JsonProperty("policy_version") String policyVersion,
            @JsonProperty("target_service") String targetService,
            @JsonProperty("payload_hash") String payloadHash) {}

    @JsonInclude(JsonInclude.Include.NON_NULL)
    /** RefundSucceeded / RefundFailed / RefundUnknown payload (docs/core-contracts.md:67). */
    public record CoreRefundResult(
            @JsonProperty("operation_id") String operationId,
            @JsonProperty("line_id") String lineId,
            String state,
            @JsonProperty("amount_minor") long amountMinor,
            @JsonProperty("provider_ref") String providerRef,
            @JsonProperty("reason_code") String reasonCode,
            @JsonProperty("aggregate_version") long aggregateVersion) {}

    @JsonInclude(JsonInclude.Include.NON_NULL)
    /** A core event envelope (docs/core-contracts.md:9, :19). */
    public record CoreEnvelope(
            @JsonProperty("event_id") String eventId,
            @JsonProperty("event_type") String eventType,
            @JsonProperty("schema_version") int schemaVersion,
            @JsonProperty("merchant_id") String merchantId,
            @JsonProperty("occurred_at") String occurredAt,
            String producer,
            String topic,
            String traceparent,
            @JsonProperty("causation_id") String causationId,
            Map<String, Object> payload,
            @JsonProperty("signing_key_id") String signingKeyId,
            String signature) {}

    /** A reference to one observation (docs/core-contracts.md:61). */
    public record CoreEvidenceRef(
            @JsonProperty("observation_id") String observationId,
            @JsonProperty("source_ref") String sourceRef,
            @JsonProperty("source_version") String sourceVersion,
            @JsonProperty("content_hash") String contentHash) {}

    /** A reference to one policy chunk, not just a bundle (docs/core-contracts.md:59). */
    public record CorePolicyRef(
            @JsonProperty("bundle_id") String bundleId,
            String version,
            @JsonProperty("rule_id") String ruleId,
            @JsonProperty("chunk_id") String chunkId,
            @JsonProperty("content_hash") String contentHash) {}

    /**
     * The proposal a run submits (docs/core-contracts.md:59).
     *
     * <p>{@code suggestedAmountMinor} is a {@code Long} because the member is optional and the wire
     * says "absent" by omitting it: {@code null} in the record means the member was not sent, and a
     * core proposal never sends it as an explicit JSON null.
     */
    @JsonInclude(JsonInclude.Include.NON_NULL)
    public record CoreAgentProposal(
            @JsonProperty("schema_version") int schemaVersion,
            @JsonProperty("proposal_id") String proposalId,
            @JsonProperty("run_id") String runId,
            @JsonProperty("case_id") String caseId,
            @JsonProperty("input_revision") long inputRevision,
            @JsonProperty("case_type") String caseType,
            @JsonProperty("recommended_action") String recommendedAction,
            @JsonProperty("suggested_amount_minor") Long suggestedAmountMinor,
            String summary,
            @JsonProperty("reason_codes") List<String> reasonCodes,
            @JsonProperty("evidence_refs") List<CoreEvidenceRef> evidenceRefs,
            @JsonProperty("policy_refs") List<CorePolicyRef> policyRefs,
            @JsonProperty("missing_evidence") List<String> missingEvidence) {}
}
