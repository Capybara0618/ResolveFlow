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
 * <p>{@link #claim} is one statement that either takes the event id or finds it taken — the database decides,
 * and the caller learns which from the affected-row count. Two things follow, and both matter for money: two
 * concurrent redeliveries cannot both apply (there is no read-then-write window to lose), and a duplicate is
 * an ordinary answer rather than an error.
 *
 * <p><b>Why not "plain insert, catch the duplicate-key error".</b> That is how this started, and the real
 * broker showed what it costs (C05.1c): one event delivered to several queues at once has several transactions
 * inserting the same primary key simultaneously, and InnoDB answers some of them with
 * {@code Deadlock found when trying to get lock} instead of a duplicate-key violation. Spring reports that as
 * a lock failure, not as a {@code DataIntegrityViolationException}, so the consumer treated a duplicate as a
 * transient fault and asked the broker to redeliver — which it did, into the same race. The run converged
 * eventually (exactly one reservation, which is the property that counts), but it took eighteen redeliveries
 * and three deadlocks. An upsert that says "insert, or do nothing if it is already there" removes the whole
 * exception path.
 */
@Mapper
public interface EventInboxRepository {

    /**
     * Claim the event for this consumer.
     *
     * <p>The duplicate branch <b>changes a value</b> ({@code detail}) rather than writing an equal one, and that
     * is load-bearing rather than cosmetic. Connector/J defaults to {@code CLIENT_FOUND_ROWS}, so an
     * {@code ON DUPLICATE KEY UPDATE} that sets a column to the value it already had reports <b>1</b> —
     * indistinguishable from a fresh insert, and a duplicate would then be treated as a claim and pushed into
     * the acceptance path (observed immediately when this was written as {@code event_id = event_id}). MySQL's
     * counts are 1 for an insert and 2 for an update that changed something, under either setting, so the
     * duplicate branch has to actually write. What it writes is also the useful thing to keep: the row now says
     * a duplicate delivery arrived, which is what an operator wants to know when one does.
     *
     * <p>A genuine integrity problem (a null, an oversized value) still throws, which is the difference from
     * {@code INSERT IGNORE}: that would also swallow real errors, and a money path cannot afford to misread a
     * broken write as a duplicate.
     *
     * @return 1 if this delivery claimed the event, 2 if it was already claimed
     */
    @Insert("""
            INSERT INTO event_inbox (consumer, event_id, event_type, producer, disposition, detail, received_at)
            VALUES (#{consumer}, #{eventId}, #{eventType}, #{producer}, #{disposition}, #{detail}, #{receivedAt})
            ON DUPLICATE KEY UPDATE detail = 'duplicate delivery ignored'
            """)
    int claim(
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
