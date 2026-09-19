package com.resolveflow.caseservice.casefile;

/**
 * The trajectory vocabulary, member for member with the contract's {@code TimelineEventType}.
 *
 * <p>It is an enum because the contract's enum is closed: a case view that could show a type the
 * contract does not declare would be showing something no client can interpret, and the migration's
 * CHECK constraint refuses such a row one layer lower.
 *
 * <p>Only {@code CASE_CREATED} is written so far. The others belong to the steps that produce them
 * (C06 onwards) and are declared here because they are already part of the contract, not because
 * anything emits them yet.
 */
public enum TimelineEventType {
    CASE_CREATED,
    AGENT_STARTED,
    QUESTION_REQUIRED,
    PROPOSAL_READY,
    APPROVAL_REQUIRED,
    EXECUTION_UPDATED,
    CASE_CLOSED;

    public static TimelineEventType of(String stored) {
        try {
            return valueOf(stored);
        } catch (IllegalArgumentException error) {
            throw new IllegalStateException("the database holds an unknown timeline kind: " + stored, error);
        }
    }
}
