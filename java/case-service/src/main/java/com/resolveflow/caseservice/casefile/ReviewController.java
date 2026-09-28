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
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestHeader;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

/**
 * The reviewer's surfaces: {@code GET /api/v1/review/cases} (docs/core-contracts.md:33),
 * {@code POST /api/v1/cases/{case_id}/reviews} (docs/core-contracts.md:34) and
 * {@code POST /api/v1/cases/{case_id}/manual-proposals} (docs/core-contracts.md:36).
 *
 * <p>The controller resolves the principal, hands the decision to the service, and answers with the members
 * the contract declares — with their documented spelling, because each is a declared document and not an
 * internal row. {@code If-Match} travels as its own header because that is where an ETag belongs, and it is
 * passed through as the string it arrived as: whether it is a well-formed quoted version is the service's
 * judgement (a 422 naming the header), not the framework's.
 *
 * <p>Its page meta is its own record rather than a shared one with the order listing: the order listing's
 * page is Commerce's response passed through verbatim (Commerce owns that cursor), while this cursor is
 * encoded here. Two documents that happen to look alike are not one document.
 */
@RestController
public class ReviewController {

    private final ReviewQueueService queue;
    private final ReviewDecisionService decisions;
    private final ManualProposalService manualProposals;
    private final RequestPrincipalResolver principals;

    public ReviewController(
            ReviewQueueService queue,
            ReviewDecisionService decisions,
            ManualProposalService manualProposals,
            RequestPrincipalResolver principals) {
        this.queue = queue;
        this.decisions = decisions;
        this.manualProposals = manualProposals;
        this.principals = principals;
    }

    @GetMapping("/api/v1/review/cases")
    public ResponseEntity<ReviewQueuePageResponse> list(
            @RequestHeader(name = HttpHeaders.AUTHORIZATION, required = false) String authorization,
            @RequestParam(name = "cursor", required = false) String cursor,
            @RequestParam(name = "limit", required = false) Integer limit,
            @RequestParam(name = "view", required = false) String view,
            @RequestParam(name = "query", required = false) String query) {
        AuthenticatedPrincipal principal = principals.resolve(authorization);
        return ResponseEntity.ok(ReviewQueuePageResponse.from(
                view == null && query == null
                        ? queue.list(principal, cursor, limit)
                        : queue.workspace(principal, cursor, limit, view, query)));
    }

    @PostMapping("/api/v1/cases/{case_id}/reviews")
    public ResponseEntity<ReviewResponse> decide(
            @RequestHeader(name = HttpHeaders.AUTHORIZATION, required = false) String authorization,
            @RequestHeader(name = "If-Match", required = false) String ifMatch,
            @PathVariable("case_id") String caseId,
            @RequestBody ReviewRequest request) {
        AuthenticatedPrincipal principal = principals.resolve(authorization);
        return ResponseEntity.ok(decisions.decide(principal, caseId, ifMatch, request));
    }

    @PostMapping("/api/v1/cases/{case_id}/manual-proposals")
    public ResponseEntity<ManualProposalResponse> submitManualProposal(
            @RequestHeader(name = HttpHeaders.AUTHORIZATION, required = false) String authorization,
            @PathVariable("case_id") String caseId,
            @RequestBody ManualProposalRequest request) {
        AuthenticatedPrincipal principal = principals.resolve(authorization);
        return ResponseEntity.ok(manualProposals.submit(principal, caseId, request));
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
            String description,
            @JsonProperty("requested_actions") List<RequestedAction> requestedActions) {

        static ReviewQueueItemResponse from(ReviewQueueService.ReviewQueueItem item) {
            return new ReviewQueueItemResponse(
                    item.caseId(),
                    item.status(),
                    item.inputRevision(),
                    item.version(),
                    item.updatedAt(),
                    item.lineId(),
                    item.description(),
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
