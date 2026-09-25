package com.resolveflow.commerce.order;

import org.apache.ibatis.annotations.Mapper;
import org.apache.ibatis.annotations.Param;
import org.apache.ibatis.annotations.Select;

/**
 * The read behind {@code GET /internal/v1/order-lines/{line_id}/refund-status} (C06.2c).
 *
 * <p>Lives in {@code order} rather than in {@code refund} on purpose: {@code refund} is the money path — its
 * statements take locks and move amounts — and a read-only projection has no business in a package whose other
 * files all write. This is a view over the same two tables, and putting it here keeps "which files can change
 * money" answerable by looking at one directory.
 *
 * <p><b>What it deliberately does not compute.</b> The refundable amount is paid minus refunded minus reserved,
 * and the contract says the route must not return it: a copy of a derived number is how two services start
 * disagreeing about the same money (contracts/core/openapi-commerce.yaml readLineRefundStatus). A caller that
 * wants it derives it from the three amounts returned, at the moment it needs it.
 */
@Mapper
public interface LineRefundStatusRepository {

    /**
     * One line's refund slot, with the amounts a decision is about.
     *
     * <p>One statement rather than several, for the same reason {@code RefundMoneyRepository.slotForUpdate} is
     * one: the slot's state and the ledger's amounts answer the same question, and reading them at different
     * instants would let a concurrent refund change the second after the first was seen.
     *
     * <p>{@code state}/{@code operation_id}/{@code version} come from {@code line_refund} — the slot's own
     * version, not the order line's. The order line's version moves for reasons that have nothing to do with a
     * refund, and a decision is recorded against the version of the thing it was about.
     *
     * <p>{@code LEFT JOIN} on {@code line_refund} rather than an inner join: the row exists for every line
     * (V3 seeds one per line and the acceptance path refuses a line without one), and if it ever did not, the
     * honest answer is "this line has no refund slot" — reported by the controller as a 404 — rather than a
     * missing line in a listing that looks like the line itself is unknown.
     */
    @Select("""
            SELECT l.line_id                          AS lineId,
                   l.merchant_id                      AS merchantId,
                   l.line_paid_amount                 AS linePaidAmount,
                   COALESCE(g.refunded_amount, 0)     AS refundedAmount,
                   COALESCE(g.reserved_refund_amount, 0) AS reservedRefundAmount,
                   l.currency                         AS currency,
                   r.state                            AS state,
                   r.operation_id                     AS operationId,
                   COALESCE(r.version, l.version)     AS version
              FROM order_line l
              LEFT JOIN payment_ledger g ON g.order_id = l.order_id
              LEFT JOIN line_refund r ON r.line_id = l.line_id
             WHERE l.line_id = #{lineId}
            """)
    LineRefundStatusRow findRefundStatus(@Param("lineId") String lineId);

    /**
     * One line's refund status as the route reports it.
     *
     * <p>{@code state} is null when the line has no slot, which is a fact the response has no member for: the
     * contract's {@code state} is required and its vocabulary has no "unknown". The service turns that into a
     * 404 rather than inventing a state — a made-up {@code FREE} would read as "no refund has ever been
     * reserved", which is a claim about money that nothing observed.
     */
    record LineRefundStatusRow(
            String lineId,
            String merchantId,
            long linePaidAmount,
            long refundedAmount,
            long reservedRefundAmount,
            String currency,
            String state,
            String operationId,
            long version) {}
}
