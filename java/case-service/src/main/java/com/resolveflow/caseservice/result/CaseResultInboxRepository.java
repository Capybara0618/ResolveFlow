package com.resolveflow.caseservice.result;

import java.time.Instant;
import java.util.List;
import org.apache.ibatis.annotations.Insert;
import org.apache.ibatis.annotations.Mapper;
import org.apache.ibatis.annotations.Param;
import org.apache.ibatis.annotations.Select;
import org.apache.ibatis.annotations.Update;

/**
 * The result inbox and its rejection log (V13__case_result_inbox.sql).
 *
 * <p>{@link #claim} is deliberately <em>not</em> a plain insert, although Commerce's inbox uses one. The reason
 * is the answer the caller needs: this consumer has to <em>report</em> a redelivery as a duplicate instead of
 * raising, because a duplicate is a normal outcome of an at-least-once transport rather than a failure. A plain
 * insert cannot both refuse to overwrite the claim and tell the caller that it did, so the statement is
 * {@code INSERT ... ON DUPLICATE KEY UPDATE} — MySQL reports 1 for the insert and 2 for the update it performs
 * on a duplicate, and the affected-row count is therefore the disposition, decided by the database rather than by
 * a read-then-write check that two concurrent redeliveries could both pass (docs/domain-model.md:45).
 *
 * <p><b>The duplicate branch has to change something (V14).</b> Reporting 2 depends on the update really
 * updating: with {@code detail} alone only the <em>first</em> redelivery changes anything, and every later one
 * reports 0 — or 1 under the driver's default {@code CLIENT_FOUND_ROWS}, which the caller reads as "a fresh
 * claim" — so a third delivery was silently accepted instead of being reported as a duplicate. The statement
 * therefore also does {@code deliveries = deliveries + 1}, which makes every redelivery change the row: the
 * 1-versus-2 answer stays deterministic, and the count is a fact an operator can read.
 *
 * <p>Only {@code detail} and {@code deliveries} are updated by a duplicate. Overwriting the payload columns
 * would be the bug this table exists to prevent: the same event id carrying different content is a broken
 * producer, and the row must keep what the first delivery claimed.
 */
@Mapper
public interface CaseResultInboxRepository {

    /** The disposition written by the claim: the first delivery of an event is always the accepted one. */
    String ACCEPTED = "ACCEPTED";

    /** The sentence a redelivery leaves behind, which is what makes the duplicate readable afterwards. */
    String DUPLICATE_DETAIL = "duplicate delivery ignored";

    /**
     * Claim one event id, or find that it is already claimed.
     *
     * @return 1 when this delivery claimed the event, 2 when it was already claimed (a duplicate)
     */
    @Insert("""
            INSERT INTO case_result_inbox (consumer, event_id, event_type, schema_version, merchant_id,
                                           case_id, operation_id, line_id, state, amount_minor, provider_ref,
                                           reason_code, aggregate_version, envelope, signature, signing_key_id,
                                           disposition, detail, deliveries, received_at, projected_at)
            VALUES (#{consumer}, #{eventId}, #{eventType}, #{schemaVersion}, #{merchantId},
                    #{caseId}, #{operationId}, #{lineId}, #{state}, #{amountMinor}, #{providerRef},
                    #{reasonCode}, #{aggregateVersion}, #{envelope}, #{signature}, #{signingKeyId},
                    'ACCEPTED', NULL, 1, #{receivedAt}, NULL)
            ON DUPLICATE KEY UPDATE detail = 'duplicate delivery ignored',
                                    deliveries = deliveries + 1
            """)
    int claim(
            @Param("consumer") String consumer,
            @Param("eventId") String eventId,
            @Param("eventType") String eventType,
            @Param("schemaVersion") int schemaVersion,
            @Param("merchantId") String merchantId,
            @Param("caseId") String caseId,
            @Param("operationId") String operationId,
            @Param("lineId") String lineId,
            @Param("state") String state,
            @Param("amountMinor") long amountMinor,
            @Param("providerRef") String providerRef,
            @Param("reasonCode") String reasonCode,
            @Param("aggregateVersion") long aggregateVersion,
            @Param("envelope") String envelope,
            @Param("signature") String signature,
            @Param("signingKeyId") String signingKeyId,
            @Param("receivedAt") Instant receivedAt);

    /** One claimed result, or {@code null} when this consumer never claimed that event. */
    @Select("""
            SELECT consumer          AS consumer,
                   event_id          AS eventId,
                   event_type        AS eventType,
                   schema_version    AS schemaVersion,
                   merchant_id       AS merchantId,
                   case_id           AS caseId,
                   operation_id      AS operationId,
                   line_id           AS lineId,
                   state             AS state,
                   amount_minor      AS amountMinor,
                   provider_ref      AS providerRef,
                   reason_code       AS reasonCode,
                   aggregate_version AS aggregateVersion,
                   envelope          AS envelope,
                   signature         AS signature,
                   signing_key_id    AS signingKeyId,
                   disposition       AS disposition,
                   detail            AS detail,
                   deliveries        AS deliveries,
                   received_at       AS receivedAt,
                   projected_at      AS projectedAt
              FROM case_result_inbox
             WHERE consumer = #{consumer} AND event_id = #{eventId}
            """)
    StoredResult find(@Param("consumer") String consumer, @Param("eventId") String eventId);

    /** Every result claimed for one case, oldest first: what a later projection would read. */
    @Select("""
            SELECT consumer          AS consumer,
                   event_id          AS eventId,
                   event_type        AS eventType,
                   schema_version    AS schemaVersion,
                   merchant_id       AS merchantId,
                   case_id           AS caseId,
                   operation_id      AS operationId,
                   line_id           AS lineId,
                   state             AS state,
                   amount_minor      AS amountMinor,
                   provider_ref      AS providerRef,
                   reason_code       AS reasonCode,
                   aggregate_version AS aggregateVersion,
                   envelope          AS envelope,
                   signature         AS signature,
                   signing_key_id    AS signingKeyId,
                   disposition       AS disposition,
                   detail            AS detail,
                   deliveries        AS deliveries,
                   received_at       AS receivedAt,
                   projected_at      AS projectedAt
              FROM case_result_inbox
             WHERE case_id = #{caseId}
             ORDER BY aggregate_version, received_at, event_id
            """)
    List<StoredResult> findByCase(@Param("caseId") String caseId);

    /**
     * Mark one claimed result as projected onto the case.
     *
     * <p>Unused by C05.2b-3a, which is the point of this sub-step's boundary: it exists so C05.2b-3b has one
     * statement to call, and it is conditional on {@code projected_at IS NULL} so two projection attempts
     * cannot both claim the same row.
     *
     * @return 1 when this call projected it, 0 when it was already projected (or not claimed at all)
     */
    @Update("""
            UPDATE case_result_inbox
               SET projected_at = #{projectedAt}
             WHERE consumer = #{consumer}
               AND event_id = #{eventId}
               AND projected_at IS NULL
            """)
    int markProjected(
            @Param("consumer") String consumer,
            @Param("eventId") String eventId,
            @Param("projectedAt") Instant projectedAt);

    @Insert("""
            INSERT INTO case_result_rejection (rejection_id, consumer, event_id, topic, reason, detail,
                                               raw_message, received_at)
            VALUES (#{rejectionId}, #{consumer}, #{eventId}, #{topic}, #{reason}, #{detail}, #{rawMessage},
                    #{receivedAt})
            """)
    void reject(
            @Param("rejectionId") String rejectionId,
            @Param("consumer") String consumer,
            @Param("eventId") String eventId,
            @Param("topic") String topic,
            @Param("reason") String reason,
            @Param("detail") String detail,
            @Param("rawMessage") String rawMessage,
            @Param("receivedAt") Instant receivedAt);

    @Select("""
            SELECT rejection_id AS rejectionId,
                   consumer     AS consumer,
                   event_id     AS eventId,
                   topic        AS topic,
                   reason       AS reason,
                   detail       AS detail,
                   received_at  AS receivedAt
              FROM case_result_rejection
             ORDER BY received_at, rejection_id
            """)
    List<RejectionRow> rejections();

    /** One claimed result, exactly as the table holds it. */
    record StoredResult(
            String consumer,
            String eventId,
            String eventType,
            int schemaVersion,
            String merchantId,
            String caseId,
            String operationId,
            String lineId,
            String state,
            long amountMinor,
            String providerRef,
            String reasonCode,
            long aggregateVersion,
            String envelope,
            String signature,
            String signingKeyId,
            String disposition,
            String detail,
            int deliveries,
            Instant receivedAt,
            Instant projectedAt) {}

    /** One refused message, kept rather than logged away. */
    record RejectionRow(
            String rejectionId,
            String consumer,
            String eventId,
            String topic,
            String reason,
            String detail,
            Instant receivedAt) {}
}
