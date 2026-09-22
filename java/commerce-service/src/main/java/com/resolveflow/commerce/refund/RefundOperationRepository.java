package com.resolveflow.commerce.refund;

import java.time.Instant;
import org.apache.ibatis.annotations.Insert;
import org.apache.ibatis.annotations.Mapper;
import org.apache.ibatis.annotations.Param;
import org.apache.ibatis.annotations.Select;
import org.apache.ibatis.annotations.Update;

/**
 * The refund operation rows (docs/domain-model.md:43).
 *
 * <p>Every transition is an explicit statement whose {@code WHERE} carries the state it expects, so a
 * re-entry cannot settle the same operation twice: the second attempt matches no row and reports zero rather
 * than moving money again (docs/domain-model.md:49). There is no generic update, because a generic save
 * would make a fourth state change possible without anyone deciding it should be.
 */
@Mapper
public interface RefundOperationRepository {

    @Insert("""
            INSERT INTO refund_operation (operation_id, authorization_id, case_id, input_revision, merchant_id,
                                          line_id, action, quantity, currency, amount_minor, payload_hash,
                                          policy_version, state, provider_key, provider_ref, reason_code,
                                          retry_at, reserved_at, settled_at, version)
            VALUES (#{operationId}, #{authorizationId}, #{caseId}, #{inputRevision}, #{merchantId},
                    #{lineId}, #{action}, #{quantity}, #{currency}, #{amountMinor}, #{payloadHash},
                    #{policyVersion}, #{state}, #{providerKey}, NULL, NULL,
                    NULL, #{reservedAt}, NULL, 1)
            """)
    void insert(
            @Param("operationId") String operationId,
            @Param("authorizationId") String authorizationId,
            @Param("caseId") String caseId,
            @Param("inputRevision") long inputRevision,
            @Param("merchantId") String merchantId,
            @Param("lineId") String lineId,
            @Param("action") String action,
            @Param("quantity") int quantity,
            @Param("currency") String currency,
            @Param("amountMinor") long amountMinor,
            @Param("payloadHash") String payloadHash,
            @Param("policyVersion") String policyVersion,
            @Param("state") String state,
            @Param("providerKey") String providerKey,
            @Param("reservedAt") Instant reservedAt);

    @Select("""
            SELECT operation_id     AS operationId,
                   authorization_id AS authorizationId,
                   case_id          AS caseId,
                   input_revision   AS inputRevision,
                   merchant_id      AS merchantId,
                   line_id          AS lineId,
                   action           AS action,
                   quantity         AS quantity,
                   currency         AS currency,
                   amount_minor     AS amountMinor,
                   payload_hash     AS payloadHash,
                   policy_version   AS policyVersion,
                   state            AS state,
                   provider_key     AS providerKey,
                   provider_ref     AS providerRef,
                   reason_code      AS reasonCode,
                   retry_at         AS retryAt,
                   reserved_at      AS reservedAt,
                   settled_at       AS settledAt,
                   version          AS version
              FROM refund_operation
             WHERE operation_id = #{operationId}
            """)
    StoredOperation find(@Param("operationId") String operationId);

    /**
     * The order an operation's line belongs to.
     *
     * <p>It is a join rather than a column on {@code refund_operation}: the operation row stores the line,
     * which is the fact the command carried, and the order is the line's own truth
     * (docs/domain-model.md:40). Copying it here would be a second place to read the same relationship, and
     * two places to read one fact is how they start disagreeing.
     */
    @Select("""
            SELECT l.order_id
              FROM refund_operation o
              JOIN order_line l ON l.line_id = o.line_id
             WHERE o.operation_id = #{operationId}
            """)
    String findOrderId(@Param("operationId") String operationId);

    /**
     * Settle a successful refund, from any non-terminal state.
     *
     * <p>{@code state IN ('RECEIVED','IN_PROGRESS','UNKNOWN')} is the guard, and it is in the statement
     * rather than in a check before it: a re-entered settlement finds no row, so the money can only move
     * once (docs/domain-model.md:49).
     */
    @Update("""
            UPDATE refund_operation
               SET state = 'SUCCEEDED',
                   provider_ref = #{providerRef},
                   settled_at = #{settledAt},
                   retry_at = NULL,
                   version = version + 1
             WHERE operation_id = #{operationId}
               AND state IN ('RECEIVED', 'IN_PROGRESS', 'UNKNOWN')
            """)
    int settleSucceeded(
            @Param("operationId") String operationId,
            @Param("providerRef") String providerRef,
            @Param("settledAt") Instant settledAt);

    /** Settle a determined failure, with the reason the provider gave. */
    @Update("""
            UPDATE refund_operation
               SET state = 'FAILED',
                   reason_code = #{reasonCode},
                   settled_at = #{settledAt},
                   retry_at = NULL,
                   version = version + 1
             WHERE operation_id = #{operationId}
               AND state IN ('RECEIVED', 'IN_PROGRESS', 'UNKNOWN')
            """)
    int settleFailed(
            @Param("operationId") String operationId,
            @Param("reasonCode") String reasonCode,
            @Param("settledAt") Instant settledAt);

    /**
     * Claim the right to talk to the provider about this operation.
     *
     * <p>The expected state is in the statement, so two dispatchers racing for one operation cannot both
     * reach the provider: the second matches no row and reports zero
     * (docs/domain-model.md:49, 所有终局更新检查前置状态/版本).
     */
    @Update("""
            UPDATE refund_operation
               SET state = 'IN_PROGRESS',
                   version = version + 1
             WHERE operation_id = #{operationId}
               AND state IN ('RECEIVED', 'UNKNOWN')
            """)
    int markInProgress(@Param("operationId") String operationId);

    /**
     * The operations that have waited past their retry time.
     *
     * <p>Read in the caller's transaction and then reconciled outside it: the list is a snapshot, and the
     * provider calls that follow must not hold the transaction open.
     */
    @Select("""
            SELECT operation_id
              FROM refund_operation
             WHERE state = 'UNKNOWN'
               AND (retry_at IS NULL OR retry_at <= #{now})
             ORDER BY retry_at, operation_id
             LIMIT #{limit}
            """)
    java.util.List<String> findDueForReconciliation(@Param("now") Instant now, @Param("limit") int limit);

    /** Record that the provider gave no answer, and when to ask again (C04.3 owns the retry loop). */
    @Update("""
            UPDATE refund_operation
               SET state = 'UNKNOWN',
                   reason_code = #{reasonCode},
                   retry_at = #{retryAt},
                   version = version + 1
             WHERE operation_id = #{operationId}
               AND state IN ('RECEIVED', 'IN_PROGRESS')
            """)
    int markUnknown(
            @Param("operationId") String operationId,
            @Param("reasonCode") String reasonCode,
            @Param("retryAt") Instant retryAt);

    /** One stored operation, exactly as the table holds it. */
    record StoredOperation(
            String operationId,
            String authorizationId,
            String caseId,
            long inputRevision,
            String merchantId,
            String lineId,
            String action,
            int quantity,
            String currency,
            long amountMinor,
            String payloadHash,
            String policyVersion,
            String state,
            String providerKey,
            String providerRef,
            String reasonCode,
            Instant retryAt,
            Instant reservedAt,
            Instant settledAt,
            long version) {}
}
