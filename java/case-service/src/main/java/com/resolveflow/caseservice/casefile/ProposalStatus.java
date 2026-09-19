package com.resolveflow.caseservice.casefile;

/**
 * The case-side status of a proposal, member for member with the contract's {@code ProposalStatus}.
 *
 * <p>{@code VALIDATED} is a claim about <b>this service</b>: the policy citations were re-checked against the
 * version pinned on the case and the amount was recomputed from the line's own amounts. It is not a claim
 * that the run was right, and it is not an approval — approval is C03.3's.
 *
 * <p>{@code STALE} is derived at read time from the case's current revision rather than stored (C03.2b-2):
 * a stored copy of "this is no longer current" would have to be rewritten every time a revision moves and
 * could be forgotten, while a derived one cannot.
 */
public enum ProposalStatus {
    PROPOSED,
    VALIDATED,
    STALE,
    REJECTED;

    public static ProposalStatus of(String stored) {
        try {
            return valueOf(stored);
        } catch (IllegalArgumentException error) {
            throw new IllegalStateException("the database holds an unknown proposal status: " + stored, error);
        }
    }
}
