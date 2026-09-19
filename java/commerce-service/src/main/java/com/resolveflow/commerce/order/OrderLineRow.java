package com.resolveflow.commerce.order;

import java.time.Instant;

/**
 * One order line as the read model sees it.
 *
 * <p>The members are exactly what Case's public order view needs (the core OpenAPI
 * {@code OrderLineSummary}); the owning merchant and customer are deliberately absent, because a
 * response that echoed the scope back would let a caller confirm whose row it just read.
 *
 * <p>{@code paidAt} is an {@link Instant}: the column is UTC and the driver is pinned to UTC
 * (application.yml), so the value that reaches the API is the value that was stored.
 */
public record OrderLineRow(
        String orderId,
        String lineId,
        String sku,
        String category,
        int quantity,
        long linePaidAmount,
        String currency,
        Instant paidAt,
        String status,
        long version) {}
