package com.resolveflow.caseservice.casefile;

/**
 * The one action this service may execute, member for member with the contract's {@code Action}.
 *
 * <p>Deliberately not {@link RequestedAction} (what the customer asked for) or {@link RecommendedAction}
 * (what the run proposed): those are claims other people made, and this is the claim this service is
 * prepared to act on. Keeping them apart is what makes "the proposal recommended it" unable to become "we
 * executed it" without an authorisation in between (docs/core-contracts.md:65).
 *
 * <p>Refund is the only member: reship is not a core capability (docs/core-scope.md:9), and the command
 * schema's {@code action} is a constant, so an authorisation for anything else cannot be represented.
 */
public enum ExecutableAction {
    REFUND;

    /** The wire value: lowercase-free, exactly the enum name, matching the command schema's constant. */
    public String wire() {
        return name();
    }

    /** The stored value as this service's own enum; an unknown action is a row this code cannot execute. */
    public static ExecutableAction of(String stored) {
        for (ExecutableAction action : values()) {
            if (action.name().equals(stored)) {
                return action;
            }
        }
        throw new IllegalStateException("unknown executable action in the database: " + stored);
    }
}
