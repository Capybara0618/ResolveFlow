package com.resolveflow.caseservice.casefile;

import com.fasterxml.jackson.annotation.JsonInclude;
import com.fasterxml.jackson.annotation.JsonProperty;
import java.time.Instant;

/**
 * The authorisation as the case view serves it, member for member with the contract's
 * {@code AuthorizationState}.
 *
 * <p>{@code payload_hash} and {@code planned_operation_id} are exposed on purpose: they are the two facts
 * that make the authorisation checkable rather than announced. The operation id is the one a retry reuses,
 * and the hash is over the twelve command fields, so an operator comparing the two can see that the payment
 * a human approves is the payment the command carries.
 *
 * <p>{@code expires_at} is absent whenever no expiry is set, which is currently always: core-v1.2 has no
 * expiry policy, and an authorisation stops being usable by being superseded, lapsed, revoked or consumed.
 * Absent rather than null, the same way the case view says "no proposal" and "no material".
 *
 * <p>The decision members are the record of what a person decided (C03.3b), absent while nobody has. They
 * live here rather than in the trajectory because the trajectory has no actor member: a decision readable
 * only as a summary sentence would be a fact this service stores and its readers cannot query.
 */
@JsonInclude(JsonInclude.Include.NON_NULL)
public record AuthorizationStateResponse(
        @JsonProperty("authorization_id") String authorizationId,
        @JsonProperty("authorization_version") long authorizationVersion,
        AuthorizationStatus status,
        @JsonProperty("input_revision") int inputRevision,
        ExecutableAction action,
        @JsonProperty("planned_operation_id") String plannedOperationId,
        @JsonProperty("payload_hash") String payloadHash,
        @JsonProperty("expires_at") Instant expiresAt,
        @JsonProperty("decided_by") String decidedBy,
        @JsonProperty("decided_role") String decidedRole,
        @JsonProperty("decided_at") Instant decidedAt,
        @JsonProperty("decision_reason") String decisionReason) {

    static AuthorizationStateResponse of(AuthorizationRepository.StoredAuthorization stored) {
        return new AuthorizationStateResponse(
                stored.authorizationId(),
                stored.authorizationVersion(),
                stored.authorizationStatus(),
                stored.inputRevision(),
                ExecutableAction.of(stored.action()),
                stored.plannedOperationId(),
                stored.payloadHash(),
                stored.expiresAt(),
                stored.decidedBy(),
                stored.decidedRole(),
                stored.decidedAt(),
                stored.decisionReason());
    }
}
