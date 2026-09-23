package com.resolveflow.commerce.messaging;

import java.time.Instant;
import java.util.List;
import org.apache.ibatis.annotations.Insert;
import org.apache.ibatis.annotations.Mapper;
import org.apache.ibatis.annotations.Param;
import org.apache.ibatis.annotations.Select;

/**
 * The consumer inbox and its rejection log (V4__commerce_event_inbox.sql).
 *
 * <p>{@link #claim} is a plain insert and is expected to fail on a duplicate: the primary key is the claim,
 * and letting the database refuse the second one is what keeps two concurrent redeliveries from both
 * applying. A read-then-write check would leave exactly the window this table exists to close.
 */
@Mapper
public interface EventInboxRepository {

    @Insert("""
            INSERT INTO event_inbox (consumer, event_id, event_type, producer, disposition, detail, received_at)
            VALUES (#{consumer}, #{eventId}, #{eventType}, #{producer}, #{disposition}, #{detail}, #{receivedAt})
            """)
    void claim(
            @Param("consumer") String consumer,
            @Param("eventId") String eventId,
            @Param("eventType") String eventType,
            @Param("producer") String producer,
            @Param("disposition") String disposition,
            @Param("detail") String detail,
            @Param("receivedAt") Instant receivedAt);

    @Select("""
            SELECT consumer    AS consumer,
                   event_id    AS eventId,
                   event_type  AS eventType,
                   producer    AS producer,
                   disposition AS disposition,
                   detail      AS detail,
                   received_at AS receivedAt
              FROM event_inbox
             WHERE consumer = #{consumer} AND event_id = #{eventId}
            """)
    InboxRow find(@Param("consumer") String consumer, @Param("eventId") String eventId);

    @Insert("""
            INSERT INTO event_rejection (rejection_id, consumer, event_id, topic, reason, detail, raw_message,
                                         received_at)
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
              FROM event_rejection
             ORDER BY received_at, rejection_id
            """)
    List<RejectionRow> rejections();

    /** One inbox row: what this consumer did with one event, or that it never saw it. */
    record InboxRow(
            String consumer,
            String eventId,
            String eventType,
            String producer,
            String disposition,
            String detail,
            Instant receivedAt) {}

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
