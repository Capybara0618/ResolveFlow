package com.resolveflow.caseservice.casefile;

/**
 * The case lifecycle of docs/domain-model.md:55, member for member with the core contract's
 * {@code CaseStatus} enum (contracts/core/openapi-case.yaml).
 *
 * <p>Nothing here is invented: a status the contract does not declare cannot be stored, because the
 * migration's CHECK constraint is this list.
 *
 * <p>{@code CANCELLED} exists only before the authorisation is consumed; after consumption there is
 * no cancel edge (docs/domain-model.md:36). That is why cancel is not "any non-terminal status" but is
 * decided by the code that owns the authorisation, not by {@link #isTerminal()} here.
 */
public enum CaseStatus {
    QUEUED,
    ANALYZING,
    WAITING_CUSTOMER,
    PENDING_REVIEW,
    AUTHORIZED,
    EXECUTING,
    RECONCILING,
    CLOSED_SUCCESS,
    CLOSED_REJECTED,
    CANCELLED;

    /** A terminal case holds no active slot and accepts no further input. */
    public boolean isTerminal() {
        return this == CLOSED_SUCCESS || this == CLOSED_REJECTED || this == CANCELLED;
    }

    /**
     * Whether new input can still be added at all: a new evidence record, or a person's proposal.
     *
     * <p>It is not the negation of {@link #isTerminal()}: {@code EXECUTING} and {@code RECONCILING} are not
     * terminal (money is moving and the outcome is unknown) but their input is frozen, because the payload
     * being executed was fixed from the input as it stood (docs/domain-model.md:36). The freeze is the
     * difference between "this case is over" and "this case can no longer be argued with".
     */
    public boolean acceptsNewInput() {
        return this == QUEUED
                || this == ANALYZING
                || this == WAITING_CUSTOMER
                || this == PENDING_REVIEW
                || this == AUTHORIZED;
    }

    public static CaseStatus of(String stored) {
        try {
            return valueOf(stored);
        } catch (IllegalArgumentException error) {
            throw new IllegalStateException("the database holds an unknown case status: " + stored, error);
        }
    }
}
