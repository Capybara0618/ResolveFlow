package com.resolveflow.commerce.order;

import java.time.Instant;
import java.util.List;
import org.apache.ibatis.annotations.Mapper;
import org.apache.ibatis.annotations.Param;
import org.apache.ibatis.annotations.Select;

/**
 * Reads the order lines a principal scope may see.
 *
 * <p>Every query filters on both the merchant and (when given) the customer, so there is no method
 * that reads a line without a scope: a caller cannot forget the scope, because there is nothing to
 * call without one (docs/core-contracts.md:15).
 *
 * <p>The query fetches {@code limit + 1} rows. That extra row is how the service knows whether a next
 * page exists without a second count query, and it is dropped before the page is returned.
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
            @Param("beforePaidAt") Instant beforePaidAt,
            @Param("beforeLineId") String beforeLineId,
            @Param("limitPlusOne") int limitPlusOne);
}
