package com.resolveflow.caseservice.policy;

import java.time.Instant;
import java.util.List;

/**
 * The policy a case is pinned to (docs/core-contracts.md:50).
 *
 * <p>It carries the window that chose it and the payment time it was chosen by, because those are the two
 * facts that make the choice auditable: with them, "why this version" is answered by the case itself rather
 * than by re-deriving it from a policy table that may have moved on.
 *
 * <p><b>{@code merchantId} is recorded rather than re-derived</b> (C07.1). The window was chosen from one
 * merchant's policy set, so "whose rules decided this" is part of what the pin means; re-reading it from the
 * case row later would answer with a fact the case row also has, but the manifest is the record a run is
 * dispatched with, and a run that could not see the merchant could not filter its retrieval by it.
 */
public record PolicyManifest(
        String merchantId,
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
