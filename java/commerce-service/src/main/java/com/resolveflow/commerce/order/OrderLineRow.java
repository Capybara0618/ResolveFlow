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
 *
 * <p>{@code productName} and {@code variantText} are the two presentation columns added in V7.
 * Both are nullable and both may be null for any historical row: "not provided" is the honest
 * value, and a reader falls back to the SKU rather than to an invented name
 * (tasks/dsh-reviewer/05-fields-visual.md section 2). They are read only by the listing that
 * feeds the reviewer page — deliberately not by the line-context read the refund re-check uses,
 * so a display field cannot change what a refund is computed from.
 */
public record OrderLineRow(
        String orderId,
        String lineId,
        String sku,
        String productName,
        String variantText,
        String category,
        int quantity,
        long linePaidAmount,
        String currency,
        Instant paidAt,
        String status,
        long version) {}
