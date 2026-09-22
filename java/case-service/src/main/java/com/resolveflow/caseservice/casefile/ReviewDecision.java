package com.resolveflow.caseservice.casefile;

/**
 * What a reviewer can do with an authorisation, member for member with the contract's
 * {@code ReviewRequest.decision}.
 *
 * <p>Three members and no fourth: approving is the only one that lets money move, rejecting ends the case,
 * and asking the customer for more material sends it back rather than closing it. There is deliberately no
 * "APPROVE_AND_EXECUTE": consumption is the dispatch transaction's act (C04), and folding it into a human
 * decision would make an approval claim an execution that may not have happened.
 */
public enum ReviewDecision {
    APPROVE,
    REJECT,
    REQUEST_INFO;

    public static ReviewDecision of(String submitted) {
        for (ReviewDecision decision : values()) {
            if (decision.name().equals(submitted)) {
                return decision;
            }
        }
        throw new CaseService.SemanticInvalidException(
                "unknown decision: " + submitted + "; a review is one of APPROVE, REJECT, REQUEST_INFO");
    }
}
