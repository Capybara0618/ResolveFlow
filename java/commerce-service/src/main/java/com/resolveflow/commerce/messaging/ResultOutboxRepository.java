package com.resolveflow.commerce.messaging;

import java.time.Instant;
import org.apache.ibatis.annotations.Insert;
import org.apache.ibatis.annotations.Mapper;
import org.apache.ibatis.annotations.Param;
import org.apache.ibatis.annotations.Select;

/**
 * The result events this service owes the case, written in the transaction that decided them (C05.2b).
 *
 * <p>Only the two statements this step needs are here: writing one, and reading one back. The delivery
 * statements (due rows, published, dead) arrive with the publisher that needs them — dead SQL is a liability,
 * and the status columns are already constrained by the migration so a later writer cannot invent a fourth
 * state.
 */
@Mapper
public interface ResultOutboxRepository {

    @Insert("""
            INSERT INTO event_outbox (event_id, event_type, schema_version, merchant_id, topic, producer,
                                      envelope, signature, signing_key_id, status, attempts, last_error,
                                      next_attempt_at, created_at, published_at)
            VALUES (#{eventId}, #{eventType}, #{schemaVersion}, #{merchantId}, #{topic}, #{producer},
                    #{envelope}, #{signature}, #{signingKeyId}, 'PENDING', 0, NULL,
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
            @Param("createdAt") Instant createdAt);

    /** The stored result event, or {@code null}. */
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
                   created_at     AS createdAt,
                   published_at   AS publishedAt
              FROM event_outbox
             WHERE event_id = #{eventId}
            """)
    StoredResult find(@Param("eventId") String eventId);

    /** A stored result row, exactly as the table holds it. */
    record StoredResult(
            String eventId,
            String eventType,
            int schemaVersion,
            String merchantId,
            String topic,
            String producer,
            String envelope,
            String signature,
            String signingKeyId,
            String status,
            Instant createdAt,
            Instant publishedAt) {}
}
