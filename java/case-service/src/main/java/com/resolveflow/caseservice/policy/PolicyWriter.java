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
        requireNoAmbiguity(draft);
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
     * A version may not make the choice ambiguous, and that is a narrower rule than "windows may not
     * overlap".
     *
     * <p>The first version of this check refused any overlap, and C03.1b's test found what that means in
     * practice: a version with no end date can never be followed by another one, because the next version
     * always overlaps it — and closing the old window would mean editing a version that is immutable by
     * design. A policy set that cannot publish a new version is not versioned, it is frozen.
     *
     * <p>So selection is by the <b>latest start</b> that is not after the payment time, respecting explicit
     * ends (see {@link PolicySelectionService}). That leaves exactly one ambiguity — two versions starting at
     * the same instant — which is refused here. Two other shapes are refused because they are a mistake
     * rather than a supersession: a version that starts before an installed one (it would rewrite history
     * instead of continuing it), and a version that crosses a window with an explicit end (the author said
     * that version ended there, and something else covering that instant contradicts them).
     *
     * <p>Read under a lock because the answer decides whether the insert happens: without it, two imports
     * running at once could each see a different set of windows and both insert.
     */
    private void requireNoAmbiguity(PolicySourceReader.Draft draft) {
        for (PolicyRepository.StoredWindow window : policies.listWindowsForUpdate()) {
            if (draft.effectiveFrom().equals(window.effectiveFrom())) {
                throw new PolicyImportService.ImportRefusedException(draft.bundleId() + " starts at "
                        + draft.effectiveFrom() + ", the same instant as " + window.bundleId()
                        + "; a payment then would have two policies and no way to choose");
            }
            if (draft.effectiveFrom().isBefore(window.effectiveFrom())) {
                throw new PolicyImportService.ImportRefusedException(draft.bundleId() + " starts at "
                        + draft.effectiveFrom() + ", before " + window.bundleId() + " at " + window.effectiveFrom()
                        + "; a version supersedes what is in force, it does not rewrite it");
            }
            boolean crossesAnExplicitEnd = window.effectiveTo() != null
                    && (draft.effectiveTo() == null || window.effectiveFrom().isBefore(draft.effectiveTo()))
                    && draft.effectiveFrom().isBefore(window.effectiveTo());
            if (crossesAnExplicitEnd) {
                throw new PolicyImportService.ImportRefusedException(draft.bundleId() + " covers "
                        + draft.effectiveFrom() + ".."
                        + (draft.effectiveTo() == null ? "open" : draft.effectiveTo()) + ", which crosses "
                        + window.bundleId() + " [" + window.effectiveFrom() + ", " + window.effectiveTo()
                        + "), a window with an explicit end");
            }
        }
    }
}
