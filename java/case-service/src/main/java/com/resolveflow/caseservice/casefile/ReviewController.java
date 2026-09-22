package com.resolveflow.caseservice.casefile;

import com.fasterxml.jackson.annotation.JsonInclude;
import com.fasterxml.jackson.annotation.JsonProperty;
import com.resolveflow.caseservice.order.RequestPrincipalResolver;
import com.resolveflow.shared.security.AuthenticatedPrincipal;
import java.time.Instant;
import java.util.List;
import org.springframework.http.HttpHeaders;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestHeader;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

/**
 * {@code GET /api/v1/review/cases} (docs/core-contracts.md:33).
 *
 * <p>The controller resolves the principal, asks the service for one page and answers with the members the
 * contract's {@code ReviewQueueItem} declares — with their documented spelling, because the item is a
 * declared document and not an internal row.
 *
 * <p>Its page meta is its own record rather than a shared one with the order listing: the order listing's
 * page is Commerce's response passed through verbatim (Commerce owns that cursor), while this cursor is
 * encoded here. Two documents that happen to look alike are not one document.
 */
@RestController
@RequestMapping("/api/v1/review")
public class ReviewController {

    private final ReviewQueueService queue;
    private final RequestPrincipalResolver principals;

    public ReviewController(ReviewQueueService queue, RequestPrincipalResolver principals) {
        this.queue = queue;
        this.principals = principals;
    }

    @GetMapping("/cases")
    public ResponseEntity<ReviewQueuePageResponse> list(
            @RequestHeader(name = HttpHeaders.AUTHORIZATION, required = false) String authorization,
            @RequestParam(name = "cursor", required = false) String cursor,
            @RequestParam(name = "limit", required = false) Integer limit) {
        AuthenticatedPrincipal principal = principals.resolve(authorization);
        return ResponseEntity.ok(ReviewQueuePageResponse.from(queue.list(principal, cursor, limit)));
    }

    public record ReviewQueuePageResponse(List<ReviewQueueItemResponse> items, PageMeta page) {

        static ReviewQueuePageResponse from(ReviewQueueService.Page page) {
            return new ReviewQueuePageResponse(
                    page.items().stream().map(ReviewQueueItemResponse::from).toList(),
                    new PageMeta(page.nextCursor(), page.limit()));
        }
    }

    /** One queue row, member for member with the contract's {@code ReviewQueueItem}. */
    public record ReviewQueueItemResponse(
            @JsonProperty("case_id") String caseId,
            CaseStatus status,
            @JsonProperty("input_revision") int inputRevision,
            long version,
            @JsonProperty("updated_at") Instant updatedAt,
            @JsonProperty("line_id") String lineId,
            @JsonProperty("requested_actions") List<RequestedAction> requestedActions) {

        static ReviewQueueItemResponse from(ReviewQueueService.ReviewQueueItem item) {
            return new ReviewQueueItemResponse(
                    item.caseId(),
                    item.status(),
                    item.inputRevision(),
                    item.version(),
                    item.updatedAt(),
                    item.lineId(),
                    item.requestedActions());
        }
    }

    /**
     * The page cursor and bound.
     *
     * <p>{@code next_cursor} is omitted when the queue ends, and the contract allows either spelling
     * ({@code type: [string, 'null']}) — this service keeps one way to say "nothing more", the same way it
     * keeps one way to say "no amount".
     */
    @JsonInclude(JsonInclude.Include.NON_NULL)
    public record PageMeta(@JsonProperty("next_cursor") String nextCursor, int limit) {}
}
