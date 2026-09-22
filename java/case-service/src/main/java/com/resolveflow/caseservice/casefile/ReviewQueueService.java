package com.resolveflow.caseservice.casefile;

import com.resolveflow.shared.security.AuthenticatedPrincipal;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import org.springframework.stereotype.Service;

/**
 * The reviewer's queue (docs/core-contracts.md:33).
 *
 * <p>It is a read of the cases this merchant has waiting on a human decision, and it deliberately owns no
 * state: the filter is the case status, the scope is the verified principal's merchant, and the page is a
 * keyset over {@code (updated_at, case_id)}. Nothing here decides anything — approval is
 * {@code POST /api/v1/cases/{case_id}/reviews} (C03.3) — which is why a row carries only what a reviewer
 * needs to pick a case.
 *
 * <p>A customer is refused (403) rather than served an empty page. An empty page would be a lie about the
 * merchant's queue, and the contract declares 403 for this route: the queue is merchant staff's view, and
 * a customer-scoped principal has no merchant queue to read.
 */
@Service
public class ReviewQueueService {

    /** The core OpenAPI caps limit at 100 and defaults it to 20 (the same bound the order listing uses). */
    public static final int DEFAULT_LIMIT = 20;

    public static final int MAX_LIMIT = 100;

    /** One page of the queue, with the cursor that continues it and the limit actually applied. */
    public record Page(List<ReviewQueueItem> items, String nextCursor, int limit) {}

    /**
     * One row as the API serves it: the case facts plus the actions its customer asked for.
     *
     * <p>{@code requestedActions} is part of the row because a reviewer picking a case needs to know what
     * was asked for; it comes from the same case, so grouping it in here cannot disagree with the case.
     */
    public record ReviewQueueItem(
            String caseId,
            CaseStatus status,
            int inputRevision,
            long version,
            java.time.Instant updatedAt,
            String lineId,
            List<RequestedAction> requestedActions) {}

    private final CaseRepository cases;

    public ReviewQueueService(CaseRepository cases) {
        this.cases = cases;
    }

    public Page list(AuthenticatedPrincipal principal, String cursor, Integer requestedLimit) {
        if (principal.role() == com.resolveflow.shared.security.Role.CUSTOMER) {
            throw new CaseService.ForbiddenScopeException(
                    "the review queue belongs to a merchant's staff; a customer-scoped token has no queue"
                            + " to read");
        }
        int limit = normaliseLimit(requestedLimit);
        ReviewQueueCursor after = ReviewQueueCursor.decode(cursor);
        List<ReviewQueueRow> rows = cases.findReviewQueue(
                principal.merchantId(),
                after == null ? null : after.updatedAt(),
                after == null ? null : after.caseId(),
                limit + 1);
        boolean hasMore = rows.size() > limit;
        List<ReviewQueueRow> page = hasMore ? List.copyOf(rows.subList(0, limit)) : List.copyOf(rows);
        return new Page(items(page), ReviewQueueCursor.after(page, hasMore), limit);
    }

    private List<ReviewQueueItem> items(List<ReviewQueueRow> page) {
        if (page.isEmpty()) {
            return List.of();
        }
        Map<String, List<RequestedAction>> actions = new LinkedHashMap<>();
        List<String> caseIds = new ArrayList<>();
        for (ReviewQueueRow row : page) {
            caseIds.add(row.caseId());
            actions.put(row.caseId(), new ArrayList<>());
        }
        for (CaseRepository.RequestedActionRow requested : cases.findRequestedActionsFor(caseIds)) {
            actions.computeIfAbsent(requested.caseId(), key -> new ArrayList<>())
                    .add(RequestedAction.of(requested.action()));
        }
        List<ReviewQueueItem> items = new ArrayList<>();
        for (ReviewQueueRow row : page) {
            items.add(new ReviewQueueItem(
                    row.caseId(),
                    row.caseStatus(),
                    row.inputRevision(),
                    row.version(),
                    row.updatedAt(),
                    row.lineId(),
                    List.copyOf(actions.getOrDefault(row.caseId(), List.of()))));
        }
        return items;
    }

    /**
     * The declared bound, enforced rather than clamped.
     *
     * <p>A clamped limit would answer a different question than the one asked, and the caller cannot tell:
     * asking for 500 and being served 100 looks exactly like a merchant with 100 cases waiting.
     */
    private static int normaliseLimit(Integer requestedLimit) {
        if (requestedLimit == null) {
            return DEFAULT_LIMIT;
        }
        if (requestedLimit < 1 || requestedLimit > MAX_LIMIT) {
            throw new InvalidPageException("limit must be between 1 and " + MAX_LIMIT + ", not " + requestedLimit);
        }
        return requestedLimit;
    }

    /** Raised for a limit outside the contract's range; the API layer answers 400. */
    public static class InvalidPageException extends RuntimeException {

        private static final long serialVersionUID = 1L;

        public InvalidPageException(String message) {
            super(message);
        }
    }
}
