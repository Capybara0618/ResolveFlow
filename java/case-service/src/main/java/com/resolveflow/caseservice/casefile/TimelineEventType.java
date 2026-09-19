package com.resolveflow.caseservice.casefile;

/**
 * The trajectory vocabulary, member for member with the contract's {@code TimelineEventType}.
 *
 * <p>It is an enum because the contract's enum is closed: a case view that could show a type the
 * contract does not declare would be showing something no client can interpret, and the migration's
 * CHECK constraint refuses such a row one layer lower.
 *
 * <p>The list is the contract's, not a wish list: {@code CASE_CREATED} is written when a case opens,
 * {@code EVIDENCE_APPENDED} when material arrives, and C03.2 writes the run's own three
 * ({@code AGENT_STARTED}, {@code QUESTION_REQUIRED}, {@code AGENT_FAILED}). The rest belong to the
 * steps that produce them and are declared here because they are already part of the contract, not
 * because anything emits them yet.
 */
public enum TimelineEventType {
    CASE_CREATED,
    /** Material arrived and the input revision moved (docs/domain-model.md:55). */
    EVIDENCE_APPENDED,
    /** The run accepted the case and started investigating. */
    AGENT_STARTED,
    /** The run ended by asking for information instead of proposing (docs/core-contracts.md:59). */
    QUESTION_REQUIRED,
    PROPOSAL_READY,
    APPROVAL_REQUIRED,
    EXECUTION_UPDATED,
    /**
     * The run ended without a question and without a proposal.
     *
     * <p>Distinct from a proposal that was refused by the re-check: there the run did its job and the
     * service disagreed, here the run could not finish at all. Whether trying again could help rides in
     * the row's detail, because it changes what happens next (queued again, or handed to a person)
     * rather than what happened.
     */
    AGENT_FAILED,
    CASE_CLOSED;

    public static TimelineEventType of(String stored) {
        try {
            return valueOf(stored);
        } catch (IllegalArgumentException error) {
            throw new IllegalStateException("the database holds an unknown timeline kind: " + stored, error);
        }
    }
}
