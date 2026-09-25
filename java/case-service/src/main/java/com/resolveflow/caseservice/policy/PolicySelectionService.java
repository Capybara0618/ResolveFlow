package com.resolveflow.caseservice.policy;

import java.time.Instant;
import java.util.ArrayList;
import java.util.List;
import org.springframework.stereotype.Service;

/**
 * Chooses which policy version a case is decided under (docs/core-contracts.md:50).
 *
 * <p>The choice is by the line's <b>payment time</b>, never by "now". A refund requested in September for
 * something paid for in August is decided under the August policy, which is what "historical orders are not
 * subject to new policy" means in practice and the reason the bundles carry windows at all.
 *
 * <p>A payment time no version covers is refused rather than approximated. Borrowing the nearest version
 * would decide a real refund under rules that were not in force, and doing it silently is worse than doing
 * it: the case would look decided rather than blocked. The refusal names the payment time and what the
 * installed versions actually cover, because the operator's next question is which bundle is missing.
 *
 * <p><b>Selection is per merchant</b> (C07.1). A policy set is one merchant's rules; another merchant's
 * versions say nothing about how this one moves forward in time, so the filter is the first thing the scan
 * does rather than a tie-break. This is also what makes a second merchant possible at all: while the choice
 * was global, a second merchant could only be onboarded by publishing a bundle that no other merchant's
 * payments could ever select.
 */
@Service
public class PolicySelectionService {

    private final PolicyRepository policies;

    public PolicySelectionService(PolicyRepository policies) {
        this.policies = policies;
    }

    /** No installed version covers the payment time, so no policy can decide this case. */
    public static class PolicyUnavailableException extends RuntimeException {

        private static final long serialVersionUID = 1L;

        public PolicyUnavailableException(String message) {
            super(message);
        }
    }

    /**
     * The version in force at the payment time: the latest start that is not after it, and not closed before
     * it.
     *
     * <p>"Latest start" rather than "the window that contains it" is what lets a policy set move on. A version
     * with no end date is in force until a later version starts, which is how publishing works when the
     * previous version cannot be edited — and it is also what makes a fix possible: a version that starts
     * inside another one's open range takes over from its own start, and the older one is in force again after
     * the newer one ends, if the newer one says when it ends.
     *
     * <p>Two candidates starting at the same instant is a refusal, even though the import refuses that shape:
     * if the stored rows were edited by hand, deciding by row order is not a choice anybody made, and saying so
     * is better than picking one.
     */
    public PolicyManifest selectFor(String merchantId, Instant paidAt) {
        List<PolicyRepository.StoredWindow> covering = new ArrayList<>();
        for (PolicyRepository.StoredWindow window : policies.listEffectiveWindows()) {
            // **The merchant filter comes first and is not optional** (C07.1, docs/policy-rag.md:15). Without
            // it, "the latest start that is not after the payment" is a search over every merchant's policy
            // set, and one merchant's September version would decide another merchant's August payment. A
            // blank merchant is a caller bug, not a wildcard: treating it as one would make the filter
            // silently absent exactly where it is load-bearing.
            if (merchantId == null || merchantId.isBlank()) {
                throw new PolicyUnavailableException(
                        "a policy can only be selected for a named merchant; this call named none");
            }
            if (!window.merchantId().equals(merchantId)) {
                continue;
            }
            if (!paidAt.isBefore(window.effectiveFrom())
                    && (window.effectiveTo() == null || paidAt.isBefore(window.effectiveTo()))) {
                covering.add(window);
            }
        }
        if (covering.isEmpty()) {
            throw new PolicyUnavailableException("no policy version covers a payment at " + paidAt + " for merchant "
                    + merchantId + "; installed versions cover " + describeCoverage());
        }
        covering.sort(java.util.Comparator.comparing(PolicyRepository.StoredWindow::effectiveFrom)
                .reversed());
        PolicyRepository.StoredWindow latest = covering.get(0);
        if (covering.size() > 1 && covering.get(1).effectiveFrom().equals(latest.effectiveFrom())) {
            throw new PolicyUnavailableException("two policy versions start at " + latest.effectiveFrom()
                    + " and both cover a payment at " + paidAt + ": "
                    + covering.stream()
                            .map(PolicyRepository.StoredWindow::bundleId)
                            .toList()
                    + "; an import refuses that, so this database was changed outside the import");
        }
        return new PolicyManifest(
                merchantId,
                List.of(latest.bundleId()),
                latest.manifestHash(),
                latest.safetyEpoch(),
                latest.effectiveFrom(),
                latest.effectiveTo(),
                paidAt);
    }

    /**
     * The installed windows, in the words of someone who has to fix a missing one.
     *
     * <p>Every merchant's windows, with the merchant named: the question this answers is "which bundle is
     * missing", and after C07.1 a bundle id alone does not say whose policy set is short.
     */
    private String describeCoverage() {
        List<PolicyRepository.StoredWindow> windows = policies.listEffectiveWindows();
        if (windows.isEmpty()) {
            return "nothing at all: no policy bundle has been imported";
        }
        List<String> described = new ArrayList<>();
        for (PolicyRepository.StoredWindow window : windows) {
            described.add(window.merchantId() + "/" + window.bundleId() + " [" + window.effectiveFrom() + ", "
                    + (window.effectiveTo() == null ? "open" : window.effectiveTo()) + ")");
        }
        return String.join(", ", described);
    }
}
