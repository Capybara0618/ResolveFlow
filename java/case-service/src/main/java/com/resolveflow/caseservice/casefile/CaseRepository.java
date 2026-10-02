package com.resolveflow.caseservice.casefile;

import java.time.Instant;
import java.util.List;
import org.apache.ibatis.annotations.Delete;
import org.apache.ibatis.annotations.Insert;
import org.apache.ibatis.annotations.Mapper;
import org.apache.ibatis.annotations.Param;
import org.apache.ibatis.annotations.Select;
import org.apache.ibatis.annotations.Update;

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
            INSERT INTO aftersale_case (case_id, merchant_id, customer_id, order_id, line_id, description,
                                        status, input_revision, version, expires_at, created_at, updated_at)
            VALUES (#{caseId}, #{merchantId}, #{customerId}, #{orderId}, #{lineId}, #{description},
                    #{status}, #{inputRevision}, #{version}, #{expiresAt}, #{createdAt}, #{updatedAt})
            """)
    void insertCase(
            @Param("caseId") String caseId,
            @Param("merchantId") String merchantId,
            @Param("customerId") String customerId,
            @Param("orderId") String orderId,
            @Param("lineId") String lineId,
            @Param("description") String description,
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

    /**
     * The trajectory after a sequence number, which is how the event stream resumes and how it polls.
     *
     * <p>One read serves both: replaying from zero and asking for what is new since the last frame are the
     * same question, so the stream has no separate replay path that could disagree with its live path.
     */
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
               AND sequence > #{sequence}
             ORDER BY sequence
            """)
    List<TimelineEventRow> findTimelineAfter(@Param("caseId") String caseId, @Param("sequence") int sequence);

    /** Where one event sits in a case's trajectory, or null when this case never issued that id. */
    @Select("""
            SELECT sequence
              FROM case_timeline
             WHERE case_id = #{caseId}
               AND event_id = #{eventId}
            """)
    Integer findSequenceByEventId(@Param("caseId") String caseId, @Param("eventId") String eventId);

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
                   description    AS description,
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

    /**
     * The same row, locked for the rest of the transaction.
     *
     * <p>Appending material reads the revision, writes material at that revision plus one and bumps
     * the case, and those three must not be interleaved with another append: two submissions arriving
     * together would otherwise both claim the same revision (docs/domain-model.md:36).
     */
    @Select("""
            SELECT case_id        AS caseId,
                   merchant_id    AS merchantId,
                   customer_id    AS customerId,
                   line_id        AS lineId,
                   description    AS description,
                   order_id       AS orderId,
                   status         AS status,
                   version        AS version,
                   input_revision AS inputRevision,
                   expires_at     AS expiresAt,
                   created_at     AS createdAt,
                   updated_at     AS updatedAt
              FROM aftersale_case
             WHERE case_id = #{caseId}
               FOR UPDATE
            """)
    CaseRow findCaseForUpdate(@Param("caseId") String caseId);

    /** The highest trajectory sequence written for a case, or null when it has none. */
    @Select("""
            SELECT MAX(sequence)
              FROM case_timeline
             WHERE case_id = #{caseId}
            """)
    Integer highestSequence(@Param("caseId") String caseId);

    /**
     * The highest trajectory sequence written for a case, read <em>for update</em>, or null when it has none
     * (C05.2b-3b slice ⑤).
     *
     * <p>{@link #highestSequence} is a consistent read, so under REPEATABLE READ it answers from the transaction's
     * snapshot: two transactions appending to the same case would both be told the same "highest" and then collide
     * on the primary key — even when they already hold the case row, because a snapshot does not move. Allocation
     * therefore goes through this locking read, which sees the latest committed position and serialises the two
     * writers. Readers keep the unlocked one: only the arithmetic needs the lock.
     */
    @Select("""
            SELECT MAX(sequence)
              FROM case_timeline
             WHERE case_id = #{caseId}
             FOR UPDATE
            """)
    Integer highestSequenceForUpdate(@Param("caseId") String caseId);

    /**
     * The next position in this case's trajectory.
     *
     * <p>It wraps {@link #highestSequence} rather than leaving each writer to redo the arithmetic, because
     * five of them append trajectory rows and all five have to agree on what "next" means: a second spelling
     * of it would be a way to write two rows at one position, which the primary key would then refuse as a
     * caller's bug instead of the collision it actually is (C03.3c-1).
     *
     * <p>Allocation is a <em>locking</em> read (C05.2b-3b slice ⑤). A consistent read answers from the
     * transaction's snapshot, so two writers appending to the same case at the same time would both be told the
     * same "highest" and then collide on the primary key even when they already hold the case row — found by the
     * concurrent-delivery test rather than by reasoning. Locking here serialises them and always sees the latest
     * committed position.
     */
    default int nextTimelineSequence(String caseId) {
        Integer highest = highestSequenceForUpdate(caseId);
        return highest == null ? 1 : highest + 1;
    }

    /**
     * Move the case to CANCELLED, but only from the status it was read at.
     *
     * <p>The expected status is a condition of the write, not only of the check before it: two cancels
     * arriving together cannot both match, so at most one moves the version. Returns the rows changed,
     * and the caller treats anything but 1 as the conflict it is.
     */
    @Update("""
            UPDATE aftersale_case
               SET status = 'CANCELLED',
                   version = version + 1,
                   updated_at = #{updatedAt}
             WHERE case_id = #{caseId}
               AND status = #{expectedStatus}
            """)
    int markCancelled(
            @Param("caseId") String caseId,
            @Param("expectedStatus") String expectedStatus,
            @Param("updatedAt") java.time.Instant updatedAt);

    /**
     * Move the case to {@code newStatus} — or only bump its version — but only from the status it was read
     * at.
     *
     * <p>Same shape as {@link #markCancelled}, one transition instead of one verb: the expected status is a
     * condition of the write, so two transitions arriving together cannot both match. {@code newStatus} may
     * equal {@code expectedStatus}, which is how a delivery that only appends a trajectory row still moves the
     * version it was appended at.
     */
    @Update("""
            UPDATE aftersale_case
               SET status = #{newStatus},
                   version = version + 1,
                   updated_at = #{updatedAt}
             WHERE case_id = #{caseId}
               AND status = #{expectedStatus}
            """)
    int transition(
            @Param("caseId") String caseId,
            @Param("expectedStatus") String expectedStatus,
            @Param("newStatus") String newStatus,
            @Param("updatedAt") java.time.Instant updatedAt);

    /**
     * Move the case's input revision and its status in one statement, from the revision it was read at.
     *
     * <p>A revision move is the fact that retires everything decided from the previous revision, so it is one
     * write rather than two: a status change that committed while the revision stayed put would leave a case
     * pointing at a proposal it no longer matches, and the expected revision in the WHERE clause means two
     * submissions arriving together cannot both move it (C03.3c-1).
     */
    @Update("""
            UPDATE aftersale_case
               SET input_revision = #{newRevision},
                   status = #{newStatus},
                   version = version + 1,
                   updated_at = #{updatedAt}
             WHERE case_id = #{caseId}
               AND input_revision = #{expectedRevision}
            """)
    int advanceRevision(
            @Param("caseId") String caseId,
            @Param("expectedRevision") int expectedRevision,
            @Param("newRevision") int newRevision,
            @Param("newStatus") String newStatus,
            @Param("updatedAt") java.time.Instant updatedAt);

    /**
     * The details of the trajectory rows of one kind at one revision.
     *
     * <p>This is how the question rule is enforced without a table of its own: "this revision already asked
     * something" is a fact about the trajectory, and the trajectory is already the record of what happened.
     */
    @Select("""
            SELECT detail
              FROM case_timeline
             WHERE case_id = #{caseId}
               AND kind = #{kind}
               AND input_revision = #{inputRevision}
            """)
    List<String> findDetailsAtRevision(
            @Param("caseId") String caseId, @Param("kind") String kind, @Param("inputRevision") int inputRevision);

    /**
     * Free the line, because the case holding it has ended (docs/domain-model.md:26).
     *
     * <p>The row is the lock: while it exists the line has an active case, and deleting it is what lets
     * the same line be asked about again. It is deleted, never flagged, so there is no state in which a
     * released slot could still be read as held.
     */
    @Delete("""
            DELETE FROM active_case_slot
             WHERE merchant_id = #{merchantId}
               AND line_id = #{lineId}
            """)
    int releaseActiveSlot(@Param("merchantId") String merchantId, @Param("lineId") String lineId);

    @Select("""
            SELECT action
              FROM case_requested_action
             WHERE case_id = #{caseId}
             ORDER BY action
            """)
    List<String> findRequestedActions(@Param("caseId") String caseId);

    /**
     * The reviewer's queue: the merchant's cases that are waiting on a human decision (C03.2c).
     *
     * <p>The filter is the status, not a queue table. A {@code review_queue} table would be a second place
     * where "this case needs a person" is written down, and the two would disagree the first time a case
     * moved without it — the contract says the queue is a filter over case state for exactly this reason
     * ({@code ReviewQueuePage}: "not a second source of truth").
     *
     * <p>Order and keyset are the same pair: {@code (updated_at DESC, case_id DESC)} with the strict
     * comparison, so a case updated between two pages is not served twice. {@code limit + 1} rows are asked
     * for, because "is there another page" is a question about one row past the page and nothing else.
     */
    @Select("""
            SELECT case_id        AS caseId,
                   merchant_id    AS merchantId,
                   line_id        AS lineId,
                   description    AS description,
                   status         AS status,
                   input_revision AS inputRevision,
                   version        AS version,
                   updated_at     AS updatedAt
              FROM aftersale_case
             WHERE merchant_id = #{merchantId}
               AND status = 'PENDING_REVIEW'
               AND (#{afterUpdatedAt} IS NULL
                    OR updated_at < #{afterUpdatedAt}
                    OR (updated_at = #{afterUpdatedAt} AND case_id < #{afterCaseId}))
             ORDER BY updated_at DESC, case_id DESC
             LIMIT #{limit}
            """)
    List<ReviewQueueRow> findReviewQueue(
            @Param("merchantId") String merchantId,
            @Param("afterUpdatedAt") Instant afterUpdatedAt,
            @Param("afterCaseId") String afterCaseId,
            @Param("limit") int limit);

    @Select("""
            <script>
            SELECT case_id AS caseId, merchant_id AS merchantId, line_id AS lineId,
                   description, status, input_revision AS inputRevision, version, updated_at AS updatedAt
              FROM aftersale_case
             WHERE merchant_id = #{merchantId}
               AND status IN
               <foreach item="status" collection="statuses" open="(" separator="," close=")">#{status}</foreach>
               AND (#{query} = '' OR case_id = #{query} OR order_id = #{query}
                    OR description LIKE CONCAT('%', #{query}, '%'))
               AND (#{afterUpdatedAt} IS NULL OR updated_at &lt; #{afterUpdatedAt}
                    OR (updated_at = #{afterUpdatedAt} AND case_id &lt; #{afterCaseId}))
             ORDER BY updated_at DESC, case_id DESC LIMIT #{limit}
            </script>
            """)
    List<ReviewQueueRow> findWorkspaceCases(
            @Param("merchantId") String merchantId,
            @Param("statuses") List<String> statuses,
            @Param("query") String query,
            @Param("afterUpdatedAt") Instant afterUpdatedAt,
            @Param("afterCaseId") String afterCaseId,
            @Param("limit") int limit);

    String WORKSPACE_SEARCH = """
             WHERE c.merchant_id = #{merchantId}
               AND (#{query} = '' OR c.case_id = #{query} OR c.order_id = #{query}
                    OR LOCATE(#{query}, c.description) > 0)
            """;

    @Select("""
            <script>
            SELECT c.case_id AS caseId, c.line_id AS lineId, c.description, c.status,
                   c.input_revision AS inputRevision, c.version, c.updated_at AS updatedAt,
                   COALESCE(a.version,0) AS collaborationVersion,
                   u.username AS ownerUsername, u.display_name AS ownerDisplayName,
                   u.role AS ownerRole, u.enabled AS ownerEnabled
              FROM aftersale_case c
              LEFT JOIN case_collaboration a ON a.case_id=c.case_id
              LEFT JOIN identity_account u ON u.username=a.owner_username AND u.merchant_id=c.merchant_id
            """ + WORKSPACE_SEARCH + """
               AND c.status IN
               <foreach item="status" collection="statuses" open="(" separator="," close=")">#{status}</foreach>
               AND (#{scope}='PUBLIC' OR (#{scope}='MINE' AND a.owner_username=#{username})
                    OR (#{scope}='UNCLAIMED' AND a.owner_username IS NULL))
               AND (#{afterUpdatedAt} IS NULL OR c.updated_at &lt; #{afterUpdatedAt}
                    OR (c.updated_at = #{afterUpdatedAt} AND c.case_id &lt; #{afterCaseId}))
             ORDER BY c.updated_at DESC, c.case_id DESC LIMIT #{limit}
            </script>
            """)
    List<WorkspaceQueueRow> findOwnedWorkspaceCases(
            @Param("merchantId") String merchantId,
            @Param("username") String username,
            @Param("statuses") List<String> statuses,
            @Param("scope") String scope,
            @Param("query") String query,
            @Param("afterUpdatedAt") Instant afterUpdatedAt,
            @Param("afterCaseId") String afterCaseId,
            @Param("limit") int limit);

    @Select("""
            SELECT c.status, COUNT(*) AS total,
                   SUM(CASE WHEN a.owner_username=#{username} THEN 1 ELSE 0 END) AS mine,
                   SUM(CASE WHEN a.owner_username IS NULL THEN 1 ELSE 0 END) AS unclaimed
              FROM aftersale_case c LEFT JOIN case_collaboration a ON a.case_id=c.case_id
            """ + WORKSPACE_SEARCH + " GROUP BY c.status")
    List<WorkspaceCountRow> countWorkspaceCases(
            @Param("merchantId") String merchantId, @Param("username") String username, @Param("query") String query);

    record WorkspaceQueueRow(
            String caseId,
            String lineId,
            String description,
            String status,
            int inputRevision,
            long version,
            Instant updatedAt,
            long collaborationVersion,
            String ownerUsername,
            String ownerDisplayName,
            String ownerRole,
            Boolean ownerEnabled) {}

    record WorkspaceCountRow(String status, long total, long mine, long unclaimed) {
        long forScope(String scope) {
            return switch (scope) {
                case "MINE" -> mine;
                case "UNCLAIMED" -> unclaimed;
                default -> total;
            };
        }
    }

    /**
     * The requested actions of several cases at once.
     *
     * <p>One statement rather than one per row: the queue page is up to a hundred cases, and a reviewer's
     * page turning into a hundred and one queries is the kind of thing that only shows up under load.
     * The {@code IN} list is built by MyBatis from the parameter, so there is no string concatenation here.
     */
    @Select("""
            <script>
            SELECT case_id AS caseId, action AS action
              FROM case_requested_action
             WHERE case_id IN
               <foreach item="caseId" collection="caseIds" open="(" separator="," close=")">#{caseId}</foreach>
             ORDER BY case_id, action
            </script>
            """)
    List<RequestedActionRow> findRequestedActionsFor(@Param("caseIds") List<String> caseIds);

    /** One (case, action) pair, so a caller can group them without a second query per case. */
    record RequestedActionRow(String caseId, String action) {}

    /** The answer already given for one idempotency key, replayed verbatim rather than recomputed. */
    record StoredResponse(
            String idempotencyKey, String requestHash, int responseStatus, String responseBody, String caseId) {}
}
