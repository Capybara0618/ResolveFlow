package com.resolveflow.caseservice.casefile;

import java.time.Instant;
import org.apache.ibatis.annotations.Insert;
import org.apache.ibatis.annotations.Mapper;
import org.apache.ibatis.annotations.Param;
import org.apache.ibatis.annotations.Select;

/**
 * The case side's record that an authorisation became exactly one command (C05.2a).
 *
 * <p>The table (V12) already enforced this with a primary key on {@code authorization_id} and a unique key on
 * {@code operation_id}; what was missing until now was a writer, and the reason the writer insists on exactly
 * one inserted row is that "one authorisation, one command" is the case side's own guarantee rather than
 * Commerce's. Commerce refuses a second operation for the same id, but by then the command has been sent —
 * and a service that sent a second payment and relied on the receiver to notice would be calling its own
 * duplicate prevention somebody else's job.
 *
 * <p>{@code event_id} is a foreign key into {@code event_outbox}, and that is the whole record: the row says
 * which authorisation was spent, on which operation, by which signed envelope. It is not a queue — the outbox
 * is (V12) — and it is never updated: a command that left this service cannot be un-sent, and its later fate
 * belongs to the events Commerce sends back (C05.2b).
 */
@Mapper
public interface ExecutionCommandRepository {

    /** @return 1 when this authorisation had no command yet; 0 when it already did */
    @Insert("""
            INSERT INTO case_execution_command (authorization_id, case_id, operation_id, event_id,
                                                input_revision, created_at)
            VALUES (#{authorizationId}, #{caseId}, #{operationId}, #{eventId},
                    #{inputRevision}, #{createdAt})
            """)
    int insert(
            @Param("authorizationId") String authorizationId,
            @Param("caseId") String caseId,
            @Param("operationId") String operationId,
            @Param("eventId") String eventId,
            @Param("inputRevision") int inputRevision,
            @Param("createdAt") Instant createdAt);

    /** The command an authorisation produced, or {@code null} while it has produced none. */
    @Select("""
            SELECT authorization_id AS authorizationId,
                   case_id          AS caseId,
                   operation_id     AS operationId,
                   event_id         AS eventId,
                   input_revision   AS inputRevision,
                   created_at       AS createdAt
              FROM case_execution_command
             WHERE authorization_id = #{authorizationId}
            """)
    StoredCommand findByAuthorizationId(@Param("authorizationId") String authorizationId);

    /** A stored command row, exactly as the table holds it. */
    record StoredCommand(
            String authorizationId,
            String caseId,
            String operationId,
            String eventId,
            int inputRevision,
            Instant createdAt) {}
}
