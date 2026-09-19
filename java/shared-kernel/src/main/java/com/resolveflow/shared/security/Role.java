package com.resolveflow.shared.security;

/**
 * The roles the demonstration carries: a customer, a merchant reviewer and a local-only operator.
 *
 * <p>Authority: docs/product-spec.md:9 — CUSTOMER and REVIEWER are kept, OPERATOR exists for local
 * operations only, and there is no full IAM (docs/domain-model.md:24). The token's role decides what
 * a caller may see, so an unknown role is refused rather than mapped to a default.
 */
public enum Role {
    CUSTOMER,
    REVIEWER,
    OPERATOR;

    /** True when the role acts as one customer within a merchant rather than for the merchant. */
    public boolean isCustomerScoped() {
        return this == CUSTOMER;
    }
}
