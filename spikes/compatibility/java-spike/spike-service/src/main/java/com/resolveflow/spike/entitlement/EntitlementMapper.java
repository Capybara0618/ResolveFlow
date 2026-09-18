package com.resolveflow.spike.entitlement;

import com.resolveflow.spike.entitlement.EntitlementRows.EntitlementRow;
import com.resolveflow.spike.entitlement.EntitlementRows.LedgerRow;
import org.apache.ibatis.annotations.Mapper;
import org.apache.ibatis.annotations.Param;
import org.apache.ibatis.annotations.Select;
import org.apache.ibatis.annotations.Update;

import java.util.Optional;

/**
 * Every mutating statement is a conditional UPDATE whose affected-row count decides
 * success. That is the mechanism the money invariants rest on, so the spike exercises
 * the affected-row path rather than a read-then-write.
 */
@Mapper
public interface EntitlementMapper {

    @Select("""
            SELECT line_id, merchant_id, action, operation_id, state, version
            FROM line_entitlement
            WHERE line_id = #{lineId}
            FOR UPDATE
            """)
    Optional<EntitlementRow> lockByLine(@Param("lineId") long lineId);

    @Select("""
            SELECT order_id, paid_amount, refunded_amount, reserved_refund_amount, version
            FROM payment_ledger
            WHERE order_id = #{orderId}
            FOR UPDATE
            """)
    Optional<LedgerRow> lockLedger(@Param("orderId") long orderId);

    /** Non-locking reads. MySQL refuses FOR UPDATE inside a read-only transaction. */
    @Select("""
            SELECT line_id, merchant_id, action, operation_id, state, version
            FROM line_entitlement
            WHERE line_id = #{lineId}
            """)
    Optional<EntitlementRow> selectLine(@Param("lineId") long lineId);

    @Select("""
            SELECT order_id, paid_amount, refunded_amount, reserved_refund_amount, version
            FROM payment_ledger
            WHERE order_id = #{orderId}
            """)
    Optional<LedgerRow> selectLedger(@Param("orderId") long orderId);

    /**
     * INV-01 as a single atomic statement: the row only moves when the balance still
     * holds after the reservation. The CHECK constraint is the backstop, this is the gate.
     */
    @Update("""
            UPDATE payment_ledger
               SET reserved_refund_amount = reserved_refund_amount + #{amount},
                   version = version + 1
             WHERE order_id = #{orderId}
               AND version = #{version}
               AND refunded_amount + reserved_refund_amount + #{amount} <= paid_amount
            """)
    int reserveRefundAmount(@Param("orderId") long orderId,
                            @Param("amount") long amount,
                            @Param("version") long version);

    /** INV-02: only a FREE row can be occupied, and only at the version we observed. */
    @Update("""
            UPDATE line_entitlement
               SET state = 'RESERVED',
                   action = #{action},
                   operation_id = #{operationId},
                   version = version + 1
             WHERE line_id = #{lineId}
               AND version = #{version}
               AND state = 'FREE'
            """)
    int occupyIfFree(@Param("lineId") long lineId,
                     @Param("action") String action,
                     @Param("operationId") String operationId,
                     @Param("version") long version);

    /** start: RESERVED -> IN_USE. Mutually exclusive with release, which requires the same version. */
    @Update("""
            UPDATE line_entitlement
               SET state = 'IN_USE', version = version + 1
             WHERE line_id = #{lineId}
               AND version = #{version}
               AND state = 'RESERVED'
               AND operation_id = #{operationId}
            """)
    int startIfReserved(@Param("lineId") long lineId,
                        @Param("operationId") String operationId,
                        @Param("version") long version);

    /** commit: IN_USE -> CONSUMED and move reserved money into refunded, in one transaction. */
    @Update("""
            UPDATE line_entitlement
               SET state = 'CONSUMED', version = version + 1
             WHERE line_id = #{lineId}
               AND version = #{version}
               AND state = 'IN_USE'
               AND operation_id = #{operationId}
            """)
    int consumeIfInUse(@Param("lineId") long lineId,
                       @Param("operationId") String operationId,
                       @Param("version") long version);

    @Update("""
            UPDATE payment_ledger
               SET reserved_refund_amount = reserved_refund_amount - #{amount},
                   refunded_amount = refunded_amount + #{amount},
                   version = version + 1
             WHERE order_id = #{orderId}
               AND version = #{version}
               AND reserved_refund_amount >= #{amount}
            """)
    int settleRefund(@Param("orderId") long orderId,
                     @Param("amount") long amount,
                     @Param("version") long version);

    @Update("""
            INSERT INTO entitlement_operation (operation_id, line_id, action, state)
            VALUES (#{operationId}, #{lineId}, #{action}, #{state})
            """)
    int recordOperation(@Param("operationId") String operationId,
                        @Param("lineId") long lineId,
                        @Param("action") String action,
                        @Param("state") String state);

    @Select("SELECT state FROM entitlement_operation WHERE operation_id = #{operationId}")
    Optional<String> operationState(@Param("operationId") String operationId);
}