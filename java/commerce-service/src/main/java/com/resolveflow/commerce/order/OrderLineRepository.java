package com.resolveflow.commerce.order;

import java.time.Instant;
import java.util.List;
import org.apache.ibatis.annotations.Mapper;
import org.apache.ibatis.annotations.Param;
import org.apache.ibatis.annotations.Select;

/**
 * Reads the order lines a principal scope may see, and the one line a service re-checks.
 *
 * <p>The listing queries filter on both the merchant and (when given) the customer, so there is no
 * method that lists lines without a scope: a caller cannot forget the scope, because there is nothing to
 * call without one (docs/core-contracts.md:15).
 *
 * <p>{@link #findContext(String)} is the deliberate exception, and it is worth being explicit about why it
 * is not a hole: it reads by line id alone, and the contract declares it that way
 * (docs/core-contracts.md:46 — "GET /internal/v1/order-lines/{line_id}/context"). The scope check does not
 * disappear, it moves: the response carries the line's merchant and customer, and the only caller, Case,
 * compares both with the case it is re-checking before it uses any amount. What cannot happen is a *user*
 * reaching this: the {@code /internal/**} filter refuses a user token before the handler runs.
 *
 * <p>The listing query fetches {@code limit + 1} rows. That extra row is how the service knows whether a
 * next page exists without a second count query, and it is dropped before the page is returned.
 */
@Mapper
public interface OrderLineRepository {

    @Select("""
            <script>
            SELECT l.line_id           AS lineId,
                   l.order_id          AS orderId,
                   l.sku               AS sku,
                   l.category          AS category,
                   l.quantity          AS quantity,
                   l.line_paid_amount  AS linePaidAmount,
                   l.currency          AS currency,
                   l.paid_at           AS paidAt,
                   l.order_status      AS status,
                   l.version           AS version
              FROM order_line l
             WHERE l.merchant_id = #{merchantId}
            <if test="customerId != null">
               AND l.customer_id = #{customerId}
            </if>
            <if test="orderId != null">
               AND l.order_id = #{orderId}
            </if>
            <if test="lineId != null">
               AND l.line_id = #{lineId}
            </if>
            <if test="beforePaidAt != null">
               AND (l.paid_at &lt; #{beforePaidAt}
                    OR (l.paid_at = #{beforePaidAt} AND l.line_id &lt; #{beforeLineId}))
            </if>
             ORDER BY l.paid_at DESC, l.line_id DESC
             LIMIT #{limitPlusOne}
            </script>
            """)
    List<OrderLineRow> findVisible(
            @Param("merchantId") String merchantId,
            @Param("customerId") String customerId,
            @Param("orderId") String orderId,
            @Param("lineId") String lineId,
            @Param("beforePaidAt") Instant beforePaidAt,
            @Param("beforeLineId") String beforeLineId,
            @Param("limitPlusOne") int limitPlusOne);

    /**
     * One line with the ledger amounts of its order, by line id.
     *
     * <p>The ledger is joined on {@code order_id} and never on the line: {@code payment_ledger} is keyed by
     * order (docs/domain-model.md:41), and inventing a per-line split of it would be inventing money. For a
     * line whose order has no ledger row the amounts are reported as zero, which is what "no money has moved
     * yet" means — the row exists for every seeded order, and a missing one is a fact about the order, not a
     * reason to fail a read.
     */
    @Select("""
            SELECT l.line_id                AS lineId,
                   l.order_id               AS orderId,
                   l.merchant_id            AS merchantId,
                   l.customer_id            AS customerId,
                   l.sku                    AS sku,
                   l.category               AS category,
                   l.quantity               AS quantity,
                   l.line_paid_amount       AS linePaidAmount,
                   COALESCE(g.refunded_amount, 0)        AS refundedAmount,
                   COALESCE(g.reserved_refund_amount, 0) AS reservedRefundAmount,
                   l.currency               AS currency,
                   l.paid_at                AS paidAt,
                   l.order_status           AS orderStatus,
                   l.version                AS version
              FROM order_line l
              LEFT JOIN payment_ledger g ON g.order_id = l.order_id
             WHERE l.line_id = #{lineId}
            """)
    LineContextRow findContext(@Param("lineId") String lineId);
}
