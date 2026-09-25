package com.resolveflow.caseservice.casefile;

import java.time.Instant;
import java.util.List;
import org.apache.ibatis.annotations.Insert;
import org.apache.ibatis.annotations.Mapper;
import org.apache.ibatis.annotations.Param;
import org.apache.ibatis.annotations.Select;
import org.apache.ibatis.annotations.Update;

/**
 * The run binding (V15__agent_binding.sql): which run investigates which case revision.
 *
 * <p>Two statements change state and both carry their expected status, for the reason the event outbox
 * gives (docs/domain-model.md:49): two dispatch passes must not both claim one binding and move it twice.
 * Nothing here rewrites {@code run_id} — a run id that could be reassigned would name two different
 * investigations over time, and every callback already received under it would become unattributable.
 */
@Mapper
public interface AgentRunBindingRepository {

    /**
     * Record the run a case revision will be investigated by.
     *
     * <p>Called inside the transaction that opens the case, so a case cannot exist without its binding
     * (docs/domain-model.md:45). PENDING means "the Agent has not accepted it yet"; the dispatch is what
     * turns it into DISPATCHED, and it happens outside the transaction because it is a network call.
     */
    @Insert("""
            INSERT INTO agent_binding (case_id, input_revision, run_id, dispatch_status, created_at, dispatched_at)
            VALUES (#{caseId}, #{inputRevision}, #{runId}, 'PENDING', #{createdAt}, NULL)
            """)
    void insert(
            @Param("caseId") String caseId,
            @Param("inputRevision") int inputRevision,
            @Param("runId") String runId,
            @Param("createdAt") Instant createdAt);

    @Select("""
            SELECT case_id         AS caseId,
                   input_revision  AS inputRevision,
                   run_id          AS runId,
                   dispatch_status AS dispatchStatus,
                   created_at      AS createdAt,
                   dispatched_at   AS dispatchedAt
              FROM agent_binding
             WHERE case_id = #{caseId} AND input_revision = #{inputRevision}
            """)
    Binding find(@Param("caseId") String caseId, @Param("inputRevision") int inputRevision);

    /**
     * The binding a run id names, or null (C06.4④).
     *
     * <p>Needed because a tool-credential request names a run in the path and a case in the body, and the two
     * can disagree. Without this lookup the disagreement is indistinguishable from an unknown run: both would
     * come back "no such run", which tells a caller with a mistyped body that a run it can see does not exist.
     *
     * <p>{@code run_id} is unique in the table (V15__agent_binding.sql), so this returns at most one row — a run
     * id that could name two bindings would mean one investigation belonged to two case revisions.
     */
    @Select("""
            SELECT case_id         AS caseId,
                   input_revision  AS inputRevision,
                   run_id          AS runId,
                   dispatch_status AS dispatchStatus,
                   created_at      AS createdAt,
                   dispatched_at   AS dispatchedAt
              FROM agent_binding
             WHERE run_id = #{runId}
            """)
    Binding findByRunId(@Param("runId") String runId);

    /**
     * The bindings whose run the Agent has not accepted yet, oldest first.
     *
     * <p>Ordered by creation so a backlog ages visibly instead of being sampled at random, and limited so
     * one pass cannot try to deliver an unbounded number of rows while an Agent is down.
     */
    @Select("""
            SELECT case_id         AS caseId,
                   input_revision  AS inputRevision,
                   run_id          AS runId,
                   dispatch_status AS dispatchStatus,
                   created_at      AS createdAt,
                   dispatched_at   AS dispatchedAt
              FROM agent_binding
             WHERE dispatch_status = 'PENDING'
             ORDER BY created_at, case_id
             LIMIT #{limit}
            """)
    List<Binding> findPending(@Param("limit") int limit);

    /**
     * Mark a run accepted, from PENDING only.
     *
     * <p>The condition is the concurrency control: a binding another pass already dispatched is not
     * dispatched again, and this returning 0 is how the caller finds out it lost the row.
     */
    @Update("""
            UPDATE agent_binding
               SET dispatch_status = 'DISPATCHED',
                   dispatched_at = #{dispatchedAt}
             WHERE case_id = #{caseId}
               AND input_revision = #{inputRevision}
               AND dispatch_status = 'PENDING'
            """)
    int markDispatched(
            @Param("caseId") String caseId,
            @Param("inputRevision") int inputRevision,
            @Param("dispatchedAt") Instant dispatchedAt);

    @Select("""
            SELECT COUNT(*) FROM agent_binding WHERE dispatch_status = #{status}
            """)
    int countByStatus(@Param("status") String status);

    /** One binding row, as the loop reads it. */
    record Binding(
            String caseId,
            int inputRevision,
            String runId,
            String dispatchStatus,
            Instant createdAt,
            Instant dispatchedAt) {}
}
