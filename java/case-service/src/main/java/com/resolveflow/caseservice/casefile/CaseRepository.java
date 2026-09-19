package com.resolveflow.caseservice.casefile;

import java.time.Instant;
import java.util.List;
import org.apache.ibatis.annotations.Insert;
import org.apache.ibatis.annotations.Mapper;
import org.apache.ibatis.annotations.Param;
import org.apache.ibatis.annotations.Select;

/**
 * The case write and read surface, one statement per documented fact.
 *
 * <p>Slots are rows that exist only while a case is active, so {@code PRIMARY KEY (merchant_id,
 * line_id)} is what makes a second active case for one line impossible — the guarantee is the
 * database's, not a check in Java that a race could slip past (docs/domain-model.md:26). A terminal
 * case deletes its slot, which is why this table is a lock rather than a status mirror.
 */
@Mapper
public interface CaseRepository {

    @Insert("""
            INSERT INTO aftersale_case (case_id, merchant_id, customer_id, order_id, line_id, status,
                                        input_revision, version, expires_at, created_at, updated_at)
            VALUES (#{caseId}, #{merchantId}, #{customerId}, #{orderId}, #{lineId}, #{status},
                    #{inputRevision}, #{version}, #{expiresAt}, #{createdAt}, #{updatedAt})
            """)
    void insertCase(
            @Param("caseId") String caseId,
            @Param("merchantId") String merchantId,
            @Param("customerId") String customerId,
            @Param("orderId") String orderId,
            @Param("lineId") String lineId,
            @Param("status") String status,
            @Param("inputRevision") int inputRevision,
            @Param("version") long version,
            @Param("expiresAt") Instant expiresAt,
            @Param("createdAt") Instant createdAt,
            @Param("updatedAt") Instant updatedAt);

    @Insert("""
            INSERT INTO case_requested_action (case_id, action)
            VALUES (#{caseId}, #{action})
            """)
    void insertRequestedAction(@Param("caseId") String caseId, @Param("action") String action);

    /** Fails with a duplicate key when this line already has an active case. */
    @Insert("""
            INSERT INTO active_case_slot (merchant_id, line_id, case_id, created_at)
            VALUES (#{merchantId}, #{lineId}, #{caseId}, #{createdAt})
            """)
    void insertSlot(
            @Param("merchantId") String merchantId,
            @Param("lineId") String lineId,
            @Param("caseId") String caseId,
            @Param("createdAt") Instant createdAt);

    /**
     * The trajectory of what happened (docs/core-scope.md:7), appended in the same transaction as the
     * case itself: a case with no reason for existing would be a state nobody can explain.
     */
    @Insert("""
            INSERT INTO case_timeline (case_id, event_id, sequence, kind, detail, occurred_at,
                                       input_revision)
            VALUES (#{caseId}, #{eventId}, #{sequence}, #{kind}, #{detail}, #{occurredAt},
                    #{inputRevision})
            """)
    void insertTimeline(
            @Param("caseId") String caseId,
            @Param("eventId") String eventId,
            @Param("sequence") int sequence,
            @Param("kind") String kind,
            @Param("detail") String detail,
            @Param("occurredAt") Instant occurredAt,
            @Param("inputRevision") int inputRevision);

    /** The trajectory in the order it happened (docs/core-scope.md:7). */
    @Select("""
            SELECT case_id        AS caseId,
                   event_id       AS eventId,
                   sequence       AS sequence,
                   kind           AS kind,
                   detail         AS detail,
                   occurred_at    AS occurredAt,
                   input_revision AS inputRevision
              FROM case_timeline
             WHERE case_id = #{caseId}
             ORDER BY sequence
            """)
    List<TimelineEventRow> findTimeline(@Param("caseId") String caseId);

    @Insert("""
            INSERT INTO request_idempotency (merchant_id, idempotency_key, request_hash, response_status,
                                            response_body, case_id, created_at)
            VALUES (#{merchantId}, #{idempotencyKey}, #{requestHash}, #{responseStatus},
                    #{responseBody}, #{caseId}, #{createdAt})
            """)
    void insertIdempotency(
            @Param("merchantId") String merchantId,
            @Param("idempotencyKey") String idempotencyKey,
            @Param("requestHash") String requestHash,
            @Param("responseStatus") int responseStatus,
            @Param("responseBody") String responseBody,
            @Param("caseId") String caseId,
            @Param("createdAt") Instant createdAt);

    @Select("""
            SELECT idempotency_key AS idempotencyKey,
                   request_hash    AS requestHash,
                   response_status AS responseStatus,
                   response_body   AS responseBody,
                   case_id         AS caseId
              FROM request_idempotency
             WHERE merchant_id = #{merchantId}
               AND idempotency_key = #{idempotencyKey}
            """)
    StoredResponse findIdempotency(
            @Param("merchantId") String merchantId, @Param("idempotencyKey") String idempotencyKey);

    @Select("""
            SELECT case_id        AS caseId,
                   merchant_id    AS merchantId,
                   customer_id    AS customerId,
                   order_id       AS orderId,
                   line_id        AS lineId,
                   status         AS status,
                   input_revision AS inputRevision,
                   version        AS version,
                   expires_at     AS expiresAt,
                   created_at     AS createdAt,
                   updated_at     AS updatedAt
              FROM aftersale_case
             WHERE case_id = #{caseId}
            """)
    CaseRow findCase(@Param("caseId") String caseId);

    @Select("""
            SELECT action
              FROM case_requested_action
             WHERE case_id = #{caseId}
             ORDER BY action
            """)
    List<String> findRequestedActions(@Param("caseId") String caseId);

    @Select("""
            SELECT COUNT(*)
              FROM aftersale_case
             WHERE merchant_id = #{merchantId}
               AND line_id = #{lineId}
            """)
    int countCasesForLine(@Param("merchantId") String merchantId, @Param("lineId") String lineId);

    /** The answer already given for one idempotency key, replayed verbatim rather than recomputed. */
    record StoredResponse(
            String idempotencyKey, String requestHash, int responseStatus, String responseBody, String caseId) {}
}
