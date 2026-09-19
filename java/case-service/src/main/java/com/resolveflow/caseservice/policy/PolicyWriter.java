package com.resolveflow.caseservice.policy;

import java.time.Instant;
import org.springframework.stereotype.Component;
import org.springframework.transaction.annotation.Transactional;

/**
 * The transactional half of an import: check against what is stored, then store.
 *
 * <p>It is a separate component for a reason that has bitten this project's style before: a
 * {@code @Transactional} method called from another method of the same bean does not go through the proxy,
 * so it would run without a transaction and a failure halfway would leave a bundle header with no rules.
 * The checks and the writes being in one transaction is also what makes the non-overlap rule mean anything —
 * the windows are read with a lock, so two imports cannot both find the range empty.
 */
@Component
public class PolicyWriter {

    private final PolicyRepository policies;

    public PolicyWriter(PolicyRepository policies) {
        this.policies = policies;
    }

    /**
     * Stores one bundle, or reports that it was already there.
     *
     * @return true when this call inserted it, false when an identical version was already stored
     * @throws PolicyImportService.ImportRefusedException when the version exists with other content, or its
     *     window would overlap an existing one
     */
    @Transactional
    public boolean write(PolicySourceReader.Draft draft, String manifestHash, Instant importedAt) {
        PolicyRepository.StoredBundle existing = policies.findBundle(draft.bundleId());
        if (existing != null) {
            if (!existing.manifestHash().equals(manifestHash)) {
                throw new PolicyImportService.ImportRefusedException(
                        draft.bundleId() + " is already imported with hash "
                                + existing.manifestHash() + "; this file hashes to " + manifestHash
                                + ". A version is immutable — publish a new bundle_id instead.");
            }
            return false;
        }
        requireNoOverlap(draft);
        policies.insertBundle(
                draft.bundleId(),
                draft.version(),
                manifestHash,
                draft.safetyEpoch(),
                draft.effectiveFrom(),
                draft.effectiveTo(),
                importedAt,
                draft.sourcePath());
        int position = 0;
        for (PolicyRule rule : draft.rules()) {
            policies.insertRule(draft.bundleId(), rule.ruleId(), position++, rule.title(), rule.text());
        }
        return true;
    }

    /**
     * Half-open windows: a version covers {@code [from, to)}.
     *
     * <p>Read under a lock because the answer decides whether the insert happens: without it, two imports
     * running at once could each see a free range and store two versions that cover the same payment time.
     */
    private void requireNoOverlap(PolicySourceReader.Draft draft) {
        for (PolicyRepository.StoredWindow window : policies.listWindowsForUpdate()) {
            boolean overlaps = (draft.effectiveTo() == null
                            || window.effectiveFrom().isBefore(draft.effectiveTo()))
                    && (window.effectiveTo() == null || draft.effectiveFrom().isBefore(window.effectiveTo()));
            if (overlaps) {
                throw new PolicyImportService.ImportRefusedException(draft.bundleId() + " covers "
                        + draft.effectiveFrom() + ".."
                        + (draft.effectiveTo() == null ? "open" : draft.effectiveTo()) + ", which overlaps "
                        + window.bundleId() + "; selection by payment time would not be unique");
            }
        }
    }
}
