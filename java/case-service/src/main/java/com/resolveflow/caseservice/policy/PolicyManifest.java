package com.resolveflow.caseservice.policy;

import java.time.Instant;
import java.util.List;

/**
 * The policy a case is pinned to (docs/core-contracts.md:50).
 *
 * <p>It carries the window that chose it and the payment time it was chosen by, because those are the two
 * facts that make the choice auditable: with them, "why this version" is answered by the case itself rather
 * than by re-deriving it from a policy table that may have moved on.
 */
public record PolicyManifest(
        List<String> bundleIds,
        String manifestHash,
        int safetyEpoch,
        Instant effectiveFrom,
        Instant effectiveTo,
        Instant selectedByPaidAt) {

    public PolicyManifest {
        bundleIds = List.copyOf(bundleIds);
    }
}
