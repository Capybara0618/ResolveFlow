package com.resolveflow.caseservice.casefile;

import com.resolveflow.shared.security.AuthenticatedPrincipal;
import com.resolveflow.shared.security.Role;
import java.util.List;
import org.springframework.stereotype.Service;

/**
 * Reading one case (docs/core-contracts.md:29).
 *
 * <p>Visibility is the same rule as the order view: the case's own customer, or the merchant that owns
 * the line. A merchant-scoped principal sees its whole merchant's cases, because the review queue is
 * exactly that view (docs/core-contracts.md:33).
 *
 * <p>A case the principal cannot see is answered like a case that does not exist, and here that is
 * implemented literally: the same exception for both, thrown from the same place. Two different
 * answers would let anyone enumerate case ids by watching which one they got
 * (docs/core-contracts.md:27).
 *
 * <p>The trajectory is read from {@code case_timeline} in sequence order, because that is the order it
 * happened in (docs/core-scope.md:7); the stored {@code input_revision} of each event is reported, not
 * the case's current revision, so a reader can tell which revision a conclusion belonged to.
 */
@Service
public class CaseReadService {

    /** A case the principal cannot see, or one that does not exist; the caller cannot tell them apart. */
    public static class CaseNotVisibleException extends RuntimeException {

        private static final long serialVersionUID = 1L;

        public CaseNotVisibleException() {
            super("the case does not exist under this principal");
        }
    }

    private final CaseRepository cases;
    private final ProposalService proposals;
    private final EvidenceRepository evidence;

    public CaseReadService(CaseRepository cases, ProposalService proposals, EvidenceRepository evidence) {
        this.cases = cases;
        this.proposals = proposals;
        this.evidence = evidence;
    }

    public CaseSnapshotResponse read(AuthenticatedPrincipal principal, String caseId) {
        CaseRow row = cases.findCase(caseId);
        if (row == null || !visibleTo(principal, row)) {
            throw new CaseNotVisibleException();
        }
        // The proposal is read together with the case's current revision, because that is what makes a
        // proposal from an older revision come back STALE: that fact belongs to the read, not to a stored
        // copy that would have to be rewritten every time a revision moves (C03.2b-2).
        // A case with no material yet reports the member's absence rather than an empty array: the case view
        // keeps one way to say "nothing here", the same way it does for the proposal (C03.2c).
        List<CaseSnapshotResponse.EvidenceViewResponse> material = material(caseId);
        return new CaseSnapshotResponse(
                summary(row),
                proposals.view(caseId, row.inputRevision()),
                material.isEmpty() ? null : material,
                trajectory(caseId));
    }

    /**
     * The case's material, oldest first.
     *
     * <p>The store is read newest-first with the contract's own bound and then reversed, so a case that
     * somehow holds more records than the view declares (the append routes refuse to grow past the bound
     * since C03.2c, but a database upgraded from before that could) shows the most recent material rather
     * than an arbitrary prefix of the oldest.
     */
    private List<CaseSnapshotResponse.EvidenceViewResponse> material(String caseId) {
        List<EvidenceRepository.EvidenceRow> newestFirst = evidence.findRecent(caseId, CaseEvidenceService.MAX_RECORDS);
        List<CaseSnapshotResponse.EvidenceViewResponse> oldestFirst = new java.util.ArrayList<>(newestFirst.size());
        for (int index = newestFirst.size() - 1; index >= 0; index--) {
            oldestFirst.add(CaseSnapshotResponse.EvidenceViewResponse.of(newestFirst.get(index)));
        }
        return List.copyOf(oldestFirst);
    }

    private static boolean visibleTo(AuthenticatedPrincipal principal, CaseRow row) {
        if (!row.merchantId().equals(principal.merchantId())) {
            return false;
        }
        if (principal.role() == Role.CUSTOMER) {
            return row.customerId().equals(principal.customerId());
        }
        // REVIEWER and OPERATOR see the merchant's cases; the review queue is their view.
        return true;
    }

    private CaseSnapshotResponse.CaseSummaryResponse summary(CaseRow row) {
        List<RequestedAction> actions = cases.findRequestedActions(row.caseId()).stream()
                .map(RequestedAction::of)
                .toList();
        return new CaseSnapshotResponse.CaseSummaryResponse(
                row.caseId(),
                row.status(),
                row.inputRevision(),
                row.version(),
                row.createdAt(),
                row.updatedAt(),
                actions,
                row.lineId());
    }

    private List<TimelineEventView> trajectory(String caseId) {
        return cases.findTimeline(caseId).stream().map(TimelineEventView::of).toList();
    }
}
