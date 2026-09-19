package com.resolveflow.caseservice.order;

import com.fasterxml.jackson.annotation.JsonInclude;
import com.resolveflow.shared.security.AuthenticatedPrincipal;
import java.util.List;
import org.springframework.http.HttpHeaders;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.RequestHeader;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

/**
 * The public Order API (docs/core-contracts.md:26-27).
 *
 * <p>It owns the surface and Commerce owns the data: every read here is a scoped call to Commerce with
 * a service token, and the scope is the caller's own principal.
 *
 * <p>{@code GET /api/v1/orders} takes only paging parameters. The scramble for scope that the contract
 * test forbids — {@code merchant_id}, {@code customer_id}, {@code scope} — is absent by construction:
 * a customer cannot ask for another customer's lines because there is no parameter to ask with.
 *
 * <p>{@code GET /api/v1/orders/{order_id}} answers 404 for an order the principal cannot see, never
 * 403: whether another tenant's order exists is not something this surface discloses
 * (docs/core-contracts.md:27).
 */
@RestController
@RequestMapping("/api/v1/orders")
public class OrderController {

    /** Raised when the order is not visible to this principal; the API layer answers 404. */
    public static class OrderNotVisibleException extends RuntimeException {

        private static final long serialVersionUID = 1L;

        public OrderNotVisibleException() {
            super("the order does not exist under this principal");
        }
    }

    private final CommerceOrderLineClient commerce;
    private final RequestPrincipalResolver principals;

    public OrderController(CommerceOrderLineClient commerce, RequestPrincipalResolver principals) {
        this.commerce = commerce;
        this.principals = principals;
    }

    @GetMapping
    public ResponseEntity<OrderLinePageResponse> list(
            @RequestHeader(name = HttpHeaders.AUTHORIZATION, required = false) String authorization,
            @RequestParam(name = "cursor", required = false) String cursor,
            @RequestParam(name = "limit", required = false) Integer limit) {
        AuthenticatedPrincipal principal = principals.resolve(authorization);
        return ResponseEntity.ok(OrderLinePageResponse.from(commerce.list(principal, null, cursor, limit)));
    }

    @GetMapping("/{order_id}")
    public ResponseEntity<OrderLinePageResponse> readOrder(
            @RequestHeader(name = HttpHeaders.AUTHORIZATION, required = false) String authorization,
            @PathVariable("order_id") String orderId) {
        AuthenticatedPrincipal principal = principals.resolve(authorization);
        CommerceOrderLineClient.OrderLinePage page = commerce.readOrder(principal, orderId);
        if (page.items() == null || page.items().isEmpty()) {
            throw new OrderNotVisibleException();
        }
        return ResponseEntity.ok(OrderLinePageResponse.from(page));
    }

    /** The public payload: the same members Commerce returned, in the documented order and spelling. */
    public record OrderLinePageResponse(List<CommerceOrderLineClient.OrderLineSummary> items, PageMetaResponse page) {

        static OrderLinePageResponse from(CommerceOrderLineClient.OrderLinePage page) {
            int limit = page.page() == null ? 20 : page.page().limit();
            String nextCursor = page.page() == null ? null : page.page().nextCursor();
            return new OrderLinePageResponse(
                    page.items() == null ? List.of() : page.items(), new PageMetaResponse(nextCursor, limit));
        }
    }

    @JsonInclude(JsonInclude.Include.NON_NULL)
    public record PageMetaResponse(
            @com.fasterxml.jackson.annotation.JsonProperty("next_cursor")
            String nextCursor,

            int limit) {}
}
