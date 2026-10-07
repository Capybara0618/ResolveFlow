package com.resolveflow.caseservice.casefile;

import com.resolveflow.shared.security.AuthenticatedPrincipal;
import com.resolveflow.shared.security.Role;
import io.micrometer.core.instrument.MeterRegistry;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.concurrent.Semaphore;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicInteger;
import java.util.function.Supplier;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Isolation;
import org.springframework.transaction.annotation.Transactional;

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
    public record Page(List<ReviewQueueItem> items, String nextCursor, int limit, Counts counts) {
        public Page(List<ReviewQueueItem> items, String nextCursor, int limit) {
            this(items, nextCursor, limit, null);
        }
    }

    public record Counts(
            long total,

            @com.fasterxml.jackson.annotation.JsonProperty("public")
            long publicCount,

            long mine,
            long unclaimed,
            Map<String, Long> stages) {}

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
            String description,
            List<RequestedAction> requestedActions,
            CaseCollaborationService.Owner owner,
            Long collaborationVersion) {
        public ReviewQueueItem(
                String caseId,
                CaseStatus status,
                int inputRevision,
                long version,
                java.time.Instant updatedAt,
                String lineId,
                String description,
                List<RequestedAction> requestedActions) {
            this(caseId, status, inputRevision, version, updatedAt, lineId, description, requestedActions, null, null);
        }
    }

    private final CaseRepository cases;
    private final ReviewQueueCache cache;
    private final boolean cacheEnabled;
    private final MeterRegistry metrics;
    private final Semaphore databasePermits = new Semaphore(8, true);
    private final AtomicInteger databaseInflight = new AtomicInteger();
    private final AtomicInteger databasePeak = new AtomicInteger();

    public ReviewQueueService(
            CaseRepository cases,
            ReviewQueueCache cache,
            MeterRegistry metrics,
            @Value("${resolveflow.review-cache.enabled:false}") boolean cacheEnabled) {
        this.cases = cases;
        this.cache = cache;
        this.cacheEnabled = cacheEnabled;
        this.metrics = metrics;
        metrics.gauge("resolveflow.review.database.inflight", databaseInflight);
        metrics.gauge("resolveflow.review.database.peak", databasePeak);
    }

    public Page list(AuthenticatedPrincipal principal, String cursor, Integer requestedLimit) {
        CaseStaff.require(
                principal,
                "the review queue belongs to a merchant's staff; a customer-scoped token has no queue" + " to read");
        int limit = normaliseLimit(requestedLimit);
        ReviewQueueCursor after = ReviewQueueCursor.decode(cursor);
        if (cacheEnabled) {
            try {
                java.util.Optional<Page> cached = cache.find(principal.merchantId(), cursor, limit);
                if (cached.isPresent()) {
                    metrics.counter("resolveflow.review.cache", "outcome", "hit")
                            .increment();
                    return cached.get();
                }
                metrics.counter("resolveflow.review.cache", "outcome", "miss").increment();
            } catch (RuntimeException ignored) {
                metrics.counter("resolveflow.review.cache", "outcome", "error").increment();
                // Redis is not the authority. A miss/outage only changes read performance.
            }
        }
        boolean acquired = false;
        if (cacheEnabled) {
            try {
                acquired = databasePermits.tryAcquire(100, TimeUnit.MILLISECONDS);
                if (!acquired) {
                    metrics.counter("resolveflow.review.fallback", "outcome", "rejected")
                            .increment();
                    throw new ReviewQueueBusyException();
                }
            } catch (InterruptedException interrupted) {
                Thread.currentThread().interrupt();
                metrics.counter("resolveflow.review.fallback", "outcome", "interrupted")
                        .increment();
                throw new ReviewQueueBusyException();
            }
        }
        try {
            return loadFromDatabase(principal.merchantId(), cursor, after, limit);
        } finally {
            if (acquired) {
                databasePermits.release();
            }
        }
    }

    private Page loadFromDatabase(String merchantId, String cursor, ReviewQueueCursor after, int limit) {
        metrics.counter("resolveflow.review.database.queries").increment();
        List<ReviewQueueRow> rows = measuredQuery(() -> cases.findReviewQueue(
                merchantId,
                after == null ? null : after.updatedAt(),
                after == null ? null : after.caseId(),
                limit + 1));
        boolean hasMore = rows.size() > limit;
        List<ReviewQueueRow> page = hasMore ? List.copyOf(rows.subList(0, limit)) : List.copyOf(rows);
        Page result = new Page(items(page), ReviewQueueCursor.after(page, hasMore), limit);
        if (cacheEnabled) {
            try {
                cache.store(merchantId, cursor, limit, result);
            } catch (RuntimeException ignored) {
                // A failed cache write never changes the authoritative answer.
            }
        }
        return result;
    }

    /** The bounded database fallback could not admit another request in time. */
    public static class ReviewQueueBusyException extends RuntimeException {
        private static final long serialVersionUID = 1L;
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
        metrics.counter("resolveflow.review.database.queries").increment();
        for (CaseRepository.RequestedActionRow requested :
                measuredQuery(() -> cases.findRequestedActionsFor(caseIds))) {
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
                    row.description(),
                    List.copyOf(actions.getOrDefault(row.caseId(), List.of()))));
        }
        return items;
    }

    private <T> T measuredQuery(Supplier<T> query) {
        int active = databaseInflight.incrementAndGet();
        databasePeak.accumulateAndGet(active, Math::max);
        try {
            return query.get();
        } finally {
            databaseInflight.decrementAndGet();
        }
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

    @Transactional(readOnly = true, isolation = Isolation.REPEATABLE_READ)
    public Page workspace(
            AuthenticatedPrincipal principal,
            String cursor,
            Integer requestedLimit,
            String view,
            String query,
            String scope) {
        CaseStaff.require(principal, "the review workspace belongs to merchant staff");
        String term = query == null ? "" : query.trim();
        if (term.length() > 100) throw new InvalidPageException("query must be at most 100 characters");
        String stage = view == null ? "REVIEW" : view;
        String ownership = scope == null ? "PUBLIC" : scope;
        if (!List.of("PUBLIC", "MINE", "UNCLAIMED").contains(ownership))
            throw new InvalidPageException("unknown ownership scope");
        List<String> statuses = statuses(stage);
        int limit = normaliseLimit(requestedLimit);
        String context = org.springframework.util.DigestUtils.md5DigestAsHex(
                (principal.merchantId() + "\n" + principal.subject() + "\n" + stage + "\n" + ownership + "\n" + term)
                        .getBytes(java.nio.charset.StandardCharsets.UTF_8));
        ReviewQueueCursor after = ReviewQueueCursor.decodeWorkspace(cursor, context);
        List<CaseRepository.WorkspaceCountRow> counts =
                cases.countWorkspaceCases(principal.merchantId(), principal.subject(), term);
        List<CaseRepository.WorkspaceQueueRow> rows = cases.findOwnedWorkspaceCases(
                principal.merchantId(),
                principal.subject(),
                statuses,
                ownership,
                term,
                after == null ? null : after.updatedAt(),
                after == null ? null : after.caseId(),
                limit + 1);
        boolean more = rows.size() > limit;
        List<CaseRepository.WorkspaceQueueRow> page = more ? List.copyOf(rows.subList(0, limit)) : List.copyOf(rows);
        List<ReviewQueueRow> facts = page.stream()
                .map(row -> new ReviewQueueRow(
                        row.caseId(),
                        principal.merchantId(),
                        row.lineId(),
                        row.description(),
                        row.status(),
                        row.inputRevision(),
                        row.version(),
                        row.updatedAt()))
                .toList();
        List<ReviewQueueItem> items = items(facts);
        List<ReviewQueueItem> ownedItems = new ArrayList<>();
        for (int i = 0; i < page.size(); i++) {
            var row = page.get(i);
            var item = items.get(i);
            var owner = row.ownerUsername() == null
                    ? null
                    : new CaseCollaborationService.Owner(
                            row.ownerUsername(),
                            row.ownerDisplayName(),
                            Role.valueOf(row.ownerRole()),
                            Boolean.TRUE.equals(row.ownerEnabled()));
            ownedItems.add(new ReviewQueueItem(
                    item.caseId(),
                    item.status(),
                    item.inputRevision(),
                    item.version(),
                    item.updatedAt(),
                    item.lineId(),
                    item.description(),
                    item.requestedActions(),
                    owner,
                    row.collaborationVersion()));
        }
        Map<String, Long> stages = new LinkedHashMap<>();
        for (String name : List.of("REVIEW", "WAITING", "PROCESSING", "ATTENTION", "CLOSED", "ALL"))
            stages.put(
                    name,
                    counts.stream()
                            .filter(row -> statuses(name).contains(row.status()))
                            .mapToLong(row -> row.forScope(ownership))
                            .sum());
        List<CaseRepository.WorkspaceCountRow> selected =
                counts.stream().filter(row -> statuses.contains(row.status())).toList();
        Counts totals = new Counts(
                stages.get(stage),
                selected.stream()
                        .mapToLong(CaseRepository.WorkspaceCountRow::total)
                        .sum(),
                selected.stream()
                        .mapToLong(CaseRepository.WorkspaceCountRow::mine)
                        .sum(),
                selected.stream()
                        .mapToLong(CaseRepository.WorkspaceCountRow::unclaimed)
                        .sum(),
                stages);
        String next = !more || page.isEmpty()
                ? null
                : new ReviewQueueCursor(
                                page.getLast().updatedAt(), page.getLast().caseId())
                        .encodeWorkspace(context);
        return new Page(List.copyOf(ownedItems), next, limit, totals);
    }

    private static List<String> statuses(String stage) {
        return switch (stage) {
            case "REVIEW" -> List.of("PENDING_REVIEW");
            case "WAITING" -> List.of("WAITING_CUSTOMER");
            case "PROCESSING" -> List.of("QUEUED", "ANALYZING", "AUTHORIZED", "EXECUTING");
            case "ATTENTION" -> List.of("RECONCILING");
            case "CLOSED" -> List.of("CLOSED_SUCCESS", "CLOSED_REJECTED", "CANCELLED");
            case "ALL" ->
                java.util.Arrays.stream(CaseStatus.values()).map(Enum::name).toList();
            default -> throw new InvalidPageException("unknown workspace view");
        };
    }

    /** Raised for a limit outside the contract's range; the API layer answers 400. */
    public static class InvalidPageException extends RuntimeException {

        private static final long serialVersionUID = 1L;

        public InvalidPageException(String message) {
            super(message);
        }
    }
}
