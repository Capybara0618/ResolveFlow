package com.resolveflow.commerce.order;

import java.time.Instant;

/**
 * One order line with the money that has already moved against its order.
 *
 * <p>This is the row Java re-checks a refund against (docs/core-contracts.md:60): the line's own facts plus
 * the payment ledger's refunded and reserved amounts for its order. The amounts come from
 * {@code payment_ledger}, which is the authoritative money record (docs/domain-model.md:41) — reading them
 * from anywhere else would be a second opinion about the same money.
 *
 * <p>Unlike the listing's row, this one carries the owning merchant and customer. That is not the response
 * echoing a scope back: this route is service-only, and Case verifies the ownership it reports against the
 * case's own merchant and customer before using any of it. A listing that echoed the scope would let a
 * caller confirm whose row it just read; here the caller is a service that must know.
 *
 * <p>The ledger is per order and the member is per line. For the core flow they coincide: only whole,
 * unrefunded, single-line-being-refunded orders enter it, and adding up the order's refunds can only
 * overstate a line's, never understate it — the safe direction for a gate that decides whether money may
 * still be refunded.
 */
public record LineContextRow(
        String orderId,
        String lineId,
        String merchantId,
        String customerId,
        String sku,
        String category,
        int quantity,
        long linePaidAmount,
        long refundedAmount,
        long reservedRefundAmount,
        String currency,
        Instant paidAt,
        String orderStatus,
        long version) {}
