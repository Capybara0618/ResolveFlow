package com.resolveflow.caseservice.policy;

import java.time.Instant;
import java.util.List;

/**
 * One versioned rule set, as it is imported and stored (docs/core-contracts.md:50).
 *
 * <p>The effective window is part of the stored bundle but not of the contract's {@code PolicyBundle}
 * response: it is how a version is chosen for a case, not something a reader of the rules needs, and the
 * schema forbids extra members.
 *
 * <p><b>{@code merchantId} is identity rather than metadata (C07.1).</b> It is part of the manifest hash, so
 * the same wording published by two merchants is two different bundles — which is the point: a citation that
 * could not say whose policy it cited would be unverifiable by the service that has to re-check it. It *is*
 * on the wire, unlike the window, because C07.1's filter is "this run's merchant" and the Agent has to be able
 * to check the bundle it retrieved against the merchant the run was dispatched for.
 */
public record PolicyBundle(
        String bundleId,
        String merchantId,
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
