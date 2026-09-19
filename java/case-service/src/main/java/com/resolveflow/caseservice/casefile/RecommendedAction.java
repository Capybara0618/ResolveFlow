package com.resolveflow.caseservice.casefile;

/**
 * The core proposal set, member for member with the contract's {@code RecommendedAction}
 * (contracts/core/openapi-case.yaml): {@code REFUND}, {@code REQUEST_INFO}, {@code MANUAL_REVIEW},
 * {@code REJECT}.
 *
 * <p>Deliberately not {@code ContractEnums.RecommendedAction}: that one is the compat baseline and still
 * carries {@code RESHIP}, which core dropped together with the reship workflow (docs/core-scope.md). A
 * shared enum would let this service record a recommendation it cannot act on.
 */
public enum RecommendedAction {
    REFUND,
    REQUEST_INFO,
    MANUAL_REVIEW,
    REJECT;

    /** Whether this action moves money, and therefore whether an amount is recomputed for it. */
    public boolean movesMoney() {
        return this == REFUND;
    }

    public static RecommendedAction of(String proposed) {
        for (RecommendedAction action : values()) {
            if (action.name().equals(proposed)) {
                return action;
            }
        }
        throw new CaseService.SemanticInvalidException("unknown recommended_action: " + proposed);
    }
}
