package com.resolveflow.caseservice.casefile;

/**
 * The authorisation lifecycle, member for member with the contract's {@code AuthorizationStatus}
 * (docs/domain-model.md:57).
 *
 * <p>Only {@code APPROVED} and {@code CONSUMED} mean this service may execute something: an approval is a
 * human act (C03.3b), and consumption is the transaction that turns it into an operation (C04). The other
 * four are the ways an authorisation stops being usable — refused, lapsed because its input moved on,
 * withdrawn, or already spent — and they are distinct because the reason a reader needs differs in each
 * case: a rejection is a decision, a supersession is not.
 */
public enum AuthorizationStatus {
    PENDING_REVIEW,
    APPROVED,
    REJECTED,
    EXPIRED,
    REVOKED,
    CONSUMED;

    /** The stored value as this service's own enum; an unknown status is a row this code cannot reason about. */
    public static AuthorizationStatus of(String stored) {
        for (AuthorizationStatus status : values()) {
            if (status.name().equals(stored)) {
                return status;
            }
        }
        throw new IllegalStateException("unknown authorization status in the database: " + stored);
    }
}
