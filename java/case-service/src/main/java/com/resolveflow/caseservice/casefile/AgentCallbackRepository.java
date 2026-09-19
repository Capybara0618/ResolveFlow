package com.resolveflow.caseservice.casefile;

import java.time.Instant;
import org.apache.ibatis.annotations.Insert;
import org.apache.ibatis.annotations.Mapper;
import org.apache.ibatis.annotations.Param;
import org.apache.ibatis.annotations.Select;

/**
 * The callback inbox: the durable record that a delivery happened, and the thing that makes "applied at
 * most once" true.
 *
 * <p>There is no update and no delete. A delivery is inserted once and read back to answer a redelivery;
 * rewriting a disposition after the fact would mean the row no longer describes what happened when it was
 * written, which is the only thing it is for.
 */
@Mapper
public interface AgentCallbackRepository {

    /**
     * Claim a callback id.
     *
     * <p>Called first inside the delivery's transaction, so a losing race cannot have left any effect
     * behind: the insert fails, the transaction rolls back, and the caller compares hashes to decide between
     * DUPLICATE and a conflict.
     */
    @Insert("""
            INSERT INTO agent_callback (callback_id, case_id, run_id, input_revision, kind, disposition,
                                        payload_hash, traceparent, received_at)
            VALUES (#{callbackId}, #{caseId}, #{runId}, #{inputRevision}, #{kind}, #{disposition},
                    #{payloadHash}, #{traceparent}, #{receivedAt})
            """)
    void insert(
            @Param("callbackId") String callbackId,
            @Param("caseId") String caseId,
            @Param("runId") String runId,
            @Param("inputRevision") int inputRevision,
            @Param("kind") String kind,
            @Param("disposition") String disposition,
            @Param("payloadHash") String payloadHash,
            @Param("traceparent") String traceparent,
            @Param("receivedAt") Instant receivedAt);

    @Select("""
            SELECT callback_id    AS callbackId,
                   case_id        AS caseId,
                   run_id         AS runId,
                   input_revision AS inputRevision,
                   kind           AS kind,
                   disposition    AS disposition,
                   payload_hash   AS payloadHash,
                   traceparent    AS traceparent,
                   received_at    AS receivedAt
              FROM agent_callback
             WHERE callback_id = #{callbackId}
            """)
    StoredDelivery findByCallbackId(@Param("callbackId") String callbackId);

    @Select("""
            SELECT COUNT(*)
              FROM agent_callback
             WHERE case_id = #{caseId}
            """)
    int countForCase(@Param("caseId") String caseId);

    /** One recorded delivery. {@code disposition} is the first delivery's outcome: ACCEPTED or STALE. */
    record StoredDelivery(
            String callbackId,
            String caseId,
            String runId,
            int inputRevision,
            String kind,
            String disposition,
            String payloadHash,
            String traceparent,
            Instant receivedAt) {}
}
