package com.resolveflow.caseservice.outbox;

import java.time.Instant;
import java.util.List;
import org.apache.ibatis.annotations.Insert;
import org.apache.ibatis.annotations.Mapper;
import org.apache.ibatis.annotations.Param;
import org.apache.ibatis.annotations.Select;
import org.apache.ibatis.annotations.Update;

/**
 * The event outbox (V12__case_event_outbox.sql).
 *
 * <p>Every statement here keeps the same property: a row is written once by the transaction that decided the
 * event, and after that only its delivery state changes. There is no update that rewrites the envelope, the
 * signature or the event id — a signed document that could be edited after signing would make the signature a
 * decoration.
 */
@Mapper
public interface OutboxRepository {

    @Insert("""
            INSERT INTO event_outbox (event_id, event_type, schema_version, merchant_id, topic, producer,
                                      envelope, signature, signing_key_id, status, attempts, last_error,
                                      next_attempt_at, created_at, published_at)
            VALUES (#{eventId}, #{eventType}, #{schemaVersion}, #{merchantId}, #{topic}, #{producer},
                    #{envelope}, #{signature}, #{signingKeyId}, #{status}, 0, NULL,
                    NULL, #{createdAt}, NULL)
            """)
    void insert(
            @Param("eventId") String eventId,
            @Param("eventType") String eventType,
            @Param("schemaVersion") int schemaVersion,
            @Param("merchantId") String merchantId,
            @Param("topic") String topic,
            @Param("producer") String producer,
            @Param("envelope") String envelope,
            @Param("signature") String signature,
            @Param("signingKeyId") String signingKeyId,
            @Param("status") String status,
            @Param("createdAt") Instant createdAt);

    @Select("""
            SELECT event_id       AS eventId,
                   event_type     AS eventType,
                   schema_version AS schemaVersion,
                   merchant_id    AS merchantId,
                   topic          AS topic,
                   producer       AS producer,
                   envelope       AS envelope,
                   signature      AS signature,
                   signing_key_id AS signingKeyId,
                   status         AS status,
                   attempts       AS attempts,
                   last_error     AS lastError,
                   next_attempt_at AS nextAttemptAt,
                   created_at     AS createdAt,
                   published_at   AS publishedAt
              FROM event_outbox
             WHERE event_id = #{eventId}
            """)
    OutboxEvent find(@Param("eventId") String eventId);

    /**
     * The events due to be published, oldest first.
     *
     * <p>Ordered by creation rather than by event id: a command must not overtake an event that caused it, and
     * creation order is the only order this service can actually know.
     */
    @Select("""
            SELECT event_id       AS eventId,
                   event_type     AS eventType,
                   schema_version AS schemaVersion,
                   merchant_id    AS merchantId,
                   topic          AS topic,
                   producer       AS producer,
                   envelope       AS envelope,
                   signature      AS signature,
                   signing_key_id AS signingKeyId,
                   status         AS status,
                   attempts       AS attempts,
                   last_error     AS lastError,
                   next_attempt_at AS nextAttemptAt,
                   created_at     AS createdAt,
                   published_at   AS publishedAt
              FROM event_outbox
             WHERE status = 'PENDING'
               AND (next_attempt_at IS NULL OR next_attempt_at <= #{now})
             ORDER BY created_at, event_id
             LIMIT #{limit}
            """)
    List<OutboxEvent> findDue(@Param("now") Instant now, @Param("limit") int limit);

    /**
     * Mark an event published, from PENDING only.
     *
     * <p>The expected status is in the statement so two delivery loops cannot both "publish" one row and move
     * its attempt counter twice (docs/domain-model.md:49 — 所有终局更新检查前置状态/版本).
     */
    @Update("""
            UPDATE event_outbox
               SET status = 'PUBLISHED',
                   published_at = #{publishedAt},
                   attempts = attempts + 1,
                   last_error = NULL,
                   next_attempt_at = NULL
             WHERE event_id = #{eventId}
               AND status = 'PENDING'
            """)
    int markPublished(@Param("eventId") String eventId, @Param("publishedAt") Instant publishedAt);

    /** Record a failed attempt: the error, one more attempt, and when to try again. */
    @Update("""
            UPDATE event_outbox
               SET attempts = attempts + 1,
                   last_error = #{error},
                   next_attempt_at = #{nextAttemptAt}
             WHERE event_id = #{eventId}
               AND status = 'PENDING'
            """)
    int recordFailure(
            @Param("eventId") String eventId,
            @Param("error") String error,
            @Param("nextAttemptAt") Instant nextAttemptAt);

    /**
     * Give up on an event, keeping it.
     *
     * <p>DEAD rather than deleted: an event that could not be delivered is exactly the fact an operator needs,
     * and the row is what a manual replay would start from (docs/engineering.md:56 — 毒消息最终DLQ，需要操作台可追踪).
     */
    @Update("""
            UPDATE event_outbox
               SET status = 'DEAD',
                   attempts = attempts + 1,
                   last_error = #{error},
                   next_attempt_at = NULL
             WHERE event_id = #{eventId}
               AND status = 'PENDING'
            """)
    int markDead(@Param("eventId") String eventId, @Param("error") String error);

    @Select("""
            SELECT COUNT(*) FROM event_outbox WHERE status = #{status}
            """)
    int countByStatus(@Param("status") String status);
}
