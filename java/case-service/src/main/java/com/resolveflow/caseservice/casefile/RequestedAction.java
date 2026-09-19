package com.resolveflow.caseservice.casefile;

/**
 * What the customer asked for, matching the core contract's {@code RequestedAction} enum, which has
 * exactly one member: {@code REFUND}.
 *
 * <p>Reship is not a core capability (docs/core-scope.md), so this service cannot record a request for
 * it, and the migration's CHECK constraint enforces the same thing one layer lower. A request for
 * anything else is a semantic error (422), not a silently accepted no-op.
 */
public enum RequestedAction {
    REFUND;

    public static RequestedAction of(String requested) {
        for (RequestedAction action : values()) {
            if (action.name().equals(requested)) {
                return action;
            }
        }
        throw new IllegalArgumentException("core represents only the refund request, not " + requested);
    }
}
