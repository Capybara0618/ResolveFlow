package com.resolveflow.caseservice.policy;

import java.time.Instant;
import java.util.List;

/**
 * One versioned rule set, as it is imported and stored (docs/core-contracts.md:50).
 *
 * <p>The effective window is part of the stored bundle but not of the contract's {@code PolicyBundle}
 * response: it is how a version is chosen for a case, not something a reader of the rules needs, and the
 * schema forbids extra members.
 */
public record PolicyBundle(
        String bundleId,
        String version,
        String manifestHash,
        int safetyEpoch,
        Instant effectiveFrom,
        Instant effectiveTo,
        List<PolicyRule> rules) {

    /** The window contains an instant when it starts at or before it and ends after it. */
    public boolean covers(Instant instant) {
        return !instant.isBefore(effectiveFrom) && (effectiveTo == null || instant.isBefore(effectiveTo));
    }
}
