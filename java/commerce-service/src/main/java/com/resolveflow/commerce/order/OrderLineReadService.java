package com.resolveflow.commerce.order;

import java.util.List;
import org.springframework.stereotype.Service;

/**
 * The order-line listing behind Case's public order view
 * ({@code GET /internal/v1/order-lines}, added in C01.2 because the route table's Case row said its
 * order view calls Commerce but no listing route existed).
 *
 * <p>The scope is a parameter, never a request body or a header: the caller (Case) derives it from
 * the verified user token and passes it, and Commerce trusts the service token rather than the user
 * (docs/core-contracts.md:15). A customer-scoped caller passes a {@code customerId}; a merchant-scoped
 * one does not and sees the whole merchant.
 *
 * <p>When {@code customerId} is present it is combined with the merchant, so the two together are the
 * scope. There is no code path that reads by customer alone: customer identifiers are only unique
 * within a merchant, and a scope that could be satisfied by guessing a customer id would be a way to
 * read across merchants.
 */
@Service
public class OrderLineReadService {

    /** The core OpenAPI caps limit at 100 and defaults it to 20. */
    public static final int DEFAULT_LIMIT = 20;

    public static final int MAX_LIMIT = 100;

    /** What the service returns for one page of lines. */
    public record Page(List<OrderLineRow> items, String nextCursor, int limit) {}

    private final OrderLineRepository repository;

    public OrderLineReadService(OrderLineRepository repository) {
        this.repository = repository;
    }

    public Page list(String merchantId, String customerId, String cursor, Integer requestedLimit) {
        if (merchantId == null || merchantId.isBlank()) {
            throw new IllegalArgumentException("a listing needs a merchant scope");
        }
        int limit = normaliseLimit(requestedLimit);
        OrderLineCursor after = OrderLineCursor.decode(cursor);
        List<OrderLineRow> rows = repository.findVisible(
                merchantId,
                blankToNull(customerId),
                after == null ? null : after.paidAt(),
                after == null ? null : after.lineId(),
                limit + 1);
        boolean hasMore = rows.size() > limit;
        List<OrderLineRow> page = hasMore ? List.copyOf(rows.subList(0, limit)) : List.copyOf(rows);
        return new Page(page, OrderLineCursor.after(page, hasMore), limit);
    }

    private static int normaliseLimit(Integer requestedLimit) {
        if (requestedLimit == null) {
            return DEFAULT_LIMIT;
        }
        if (requestedLimit < 1 || requestedLimit > MAX_LIMIT) {
            throw new IllegalArgumentException("limit must be between 1 and " + MAX_LIMIT);
        }
        return requestedLimit;
    }

    private static String blankToNull(String value) {
        return value == null || value.isBlank() ? null : value;
    }
}
