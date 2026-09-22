package com.resolveflow.commerce.refund;

import java.time.Instant;
import org.apache.ibatis.annotations.Mapper;
import org.apache.ibatis.annotations.Param;
import org.apache.ibatis.annotations.Select;
import org.apache.ibatis.annotations.Update;

/**
 * The money side: the line's refund slot and the order's payment ledger
 * (docs/domain-model.md:41-42).
 *
 * <p>Two tables meet here and the lock order between them is fixed: the **ledger first, then the line
 * slot**. Every writer takes them in that order, so two refunds for two lines of one order cannot deadlock
 * against each other.
 *
 * <p>None of these statements checks a condition in Java before writing it. Reserving more than the order
 * still owes, holding a line somebody else holds, or refunding an already-refunded line are all refused by
 * the statement itself, so the guarantee does not depend on the reader having read the latest row
 * (docs/engineering.md:23).
 */
@Mapper
public interface RefundMoneyRepository {

    /**
     * Lock the order's ledger row for the rest of the transaction.
     *
     * <p>{@code FOR UPDATE} rather than a read: the reserve and the settle both decide from these amounts,
     * so a concurrent refund must wait here rather than act on a stale figure.
     */
    @Select("""
            SELECT order_id               AS orderId,
                   paid_amount            AS paidAmount,
                   refunded_amount        AS refundedAmount,
                   reserved_refund_amount AS reservedRefundAmount,
                   version                AS version
              FROM payment_ledger
             WHERE order_id = #{orderId}
             FOR UPDATE
            """)
    LedgerRow lockLedger(@Param("orderId") String orderId);

    /**
     * Lock the line's refund slot, and read the line facts a command is checked against.
     *
     * <p>One statement rather than two reads: the slot's state and the line's paid amount decide the same
     * decision, and reading them at different moments would let a concurrent refund change the second one
     * after the first was seen.
     */
    @Select("""
            SELECT r.line_id          AS lineId,
                   l.order_id         AS orderId,
                   l.merchant_id      AS merchantId,
                   l.quantity         AS quantity,
                   l.line_paid_amount AS linePaidAmount,
                   l.currency         AS currency,
                   r.state            AS state,
                   r.operation_id     AS holdingOperationId,
                   r.version          AS version
              FROM line_refund r
              JOIN order_line l ON l.line_id = r.line_id
             WHERE r.line_id = #{lineId}
             FOR UPDATE
            """)
    RefundSlot slotForUpdate(@Param("lineId") String lineId);

    /**
     * Reserve the line and hold it for one operation, from FREE only.
     *
     * <p>The {@code state = 'FREE'} condition is what makes "one live refund per line" hold under
     * concurrency: two operations racing for the same line both run this statement, and the second matches
     * no row. The schema's generated-column index is the backstop, not the mechanism.
     */
    @Update("""
            UPDATE line_refund
               SET state = 'RESERVED',
                   operation_id = #{operationId},
                   version = version + 1,
                   updated_at = #{at}
             WHERE line_id = #{lineId}
               AND state = 'FREE'
            """)
    int holdForRefund(
            @Param("lineId") String lineId, @Param("operationId") String operationId, @Param("at") Instant at);

    /**
     * Reserve one line's amount on the order's ledger.
     *
     * <p>The condition is the money invariant itself: the ledger must not already account for more than the
     * order was paid, checked against the amounts as this transaction just locked them. A second reservation
     * on a fully-refunded order therefore matches no row, which is how "100 concurrent refunds do not exceed
     * the paid amount" holds without a Java-side check that could race (docs/domain-model.md:41).
     */
    @Update("""
            UPDATE payment_ledger
               SET reserved_refund_amount = reserved_refund_amount + #{amountMinor},
                   version = version + 1
             WHERE order_id = #{orderId}
               AND refunded_amount + reserved_refund_amount + #{amountMinor} <= paid_amount
            """)
    int reserveInLedger(@Param("orderId") String orderId, @Param("amountMinor") long amountMinor);

    /**
     * Move one line's reserved money into the ledger's refunded column, on success.
     *
     * <p>The three conditions are the money invariant in one place: this order must still hold the
     * reservation, must not already account for more than it was paid, and must have the reservation to
     * release. Any of them failing means this transaction is operating on a world it did not read.
     */
    @Update("""
            UPDATE payment_ledger
               SET refunded_amount = refunded_amount + #{amountMinor},
                   reserved_refund_amount = reserved_refund_amount - #{amountMinor},
                   version = version + 1
             WHERE order_id = #{orderId}
               AND reserved_refund_amount >= #{amountMinor}
               AND refunded_amount + reserved_refund_amount <= paid_amount
            """)
    int consumeReservation(@Param("orderId") String orderId, @Param("amountMinor") long amountMinor);

    /**
     * Release one line's reservation, on a determined failure.
     *
     * <p>It does not touch {@code refunded_amount}: a failed refund moved no money, so the only thing that
     * changes is that the line stops holding it (docs/domain-model.md:49).
     */
    @Update("""
            UPDATE payment_ledger
               SET reserved_refund_amount = reserved_refund_amount - #{amountMinor},
                   version = version + 1
             WHERE order_id = #{orderId}
               AND reserved_refund_amount >= #{amountMinor}
            """)
    int releaseReservation(@Param("orderId") String orderId, @Param("amountMinor") long amountMinor);

    /** Finish a line: the refund succeeded, so this line can never be refunded again. */
    @Update("""
            UPDATE line_refund
               SET state = 'CONSUMED',
                   version = version + 1,
                   updated_at = #{at}
             WHERE line_id = #{lineId}
               AND state = 'RESERVED'
               AND operation_id = #{operationId}
            """)
    int consumeSlot(@Param("lineId") String lineId, @Param("operationId") String operationId, @Param("at") Instant at);

    /**
     * Free a line after a determined failure, keeping the operation that held it out of the row.
     *
     * <p>{@code operation_id = NULL} is required by the slot's own CHECK: a FREE slot names nobody. The
     * operation row still remembers which line it was for, so clearing this does not lose history.
     */
    @Update("""
            UPDATE line_refund
               SET state = 'FREE',
                   operation_id = NULL,
                   version = version + 1,
                   updated_at = #{at}
             WHERE line_id = #{lineId}
               AND state = 'RESERVED'
               AND operation_id = #{operationId}
            """)
    int releaseSlot(@Param("lineId") String lineId, @Param("operationId") String operationId, @Param("at") Instant at);

    /** One ledger row: the authoritative money record for an order (docs/domain-model.md:41). */
    record LedgerRow(String orderId, long paidAmount, long refundedAmount, long reservedRefundAmount, long version) {}

    /** One line's refund slot plus the line facts a command is checked against. */
    record RefundSlot(
            String lineId,
            String orderId,
            String merchantId,
            int quantity,
            long linePaidAmount,
            String currency,
            String state,
            String holdingOperationId,
            long version) {}
}
