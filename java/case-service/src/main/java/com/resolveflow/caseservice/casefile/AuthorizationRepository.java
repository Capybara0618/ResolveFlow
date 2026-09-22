package com.resolveflow.caseservice.casefile;

import java.time.Instant;
import org.apache.ibatis.annotations.Insert;
import org.apache.ibatis.annotations.Mapper;
import org.apache.ibatis.annotations.Param;
import org.apache.ibatis.annotations.Select;

/**
 * The authorisation a human decides on (C03.3a).
 *
 * <p>Like the proposal table, this one is inserted in the transaction that produced it and is not rewritten
 * on read. What differs is that an authorisation <em>does</em> change after creation — it gets decided and
 * then consumed — so the transitions are here as explicit statements with the version bumping in the same
 * statement. There is no general update: the three transitions are the whole lifecycle
 * (docs/domain-model.md:55,57), and a generic "save" would make a fourth state change possible without
 * anyone deciding it should be.
 *
 * <p>The write methods here are used from C03.3b onwards; C03.3a only creates and reads.
 */
@Mapper
public interface AuthorizationRepository {

    @Insert("""
            INSERT INTO case_authorization (authorization_id, case_id, authorization_version, status, action,
                                            input_revision, proposal_id, planned_operation_id, payload_hash,
                                            amount_minor, quantity, currency, policy_version, expires_at,
                                            created_at, updated_at)
            VALUES (#{authorizationId}, #{caseId}, #{authorizationVersion}, #{status}, #{action},
                    #{inputRevision}, #{proposalId}, #{plannedOperationId}, #{payloadHash},
                    #{amountMinor}, #{quantity}, #{currency}, #{policyVersion}, #{expiresAt},
                    #{createdAt}, #{updatedAt})
            """)
    void insert(
            @Param("authorizationId") String authorizationId,
            @Param("caseId") String caseId,
            @Param("authorizationVersion") long authorizationVersion,
            @Param("status") String status,
            @Param("action") String action,
            @Param("inputRevision") int inputRevision,
            @Param("proposalId") String proposalId,
            @Param("plannedOperationId") String plannedOperationId,
            @Param("payloadHash") String payloadHash,
            @Param("amountMinor") long amountMinor,
            @Param("quantity") int quantity,
            @Param("currency") String currency,
            @Param("policyVersion") String policyVersion,
            @Param("expiresAt") Instant expiresAt,
            @Param("createdAt") Instant createdAt,
            @Param("updatedAt") Instant updatedAt);

    /** The authorisation a reader of this case should see: the one that was created last. */
    @Select("""
            SELECT authorization_id      AS authorizationId,
                   case_id               AS caseId,
                   authorization_version AS authorizationVersion,
                   status                AS status,
                   action                AS action,
                   input_revision        AS inputRevision,
                   proposal_id           AS proposalId,
                   planned_operation_id  AS plannedOperationId,
                   payload_hash          AS payloadHash,
                   amount_minor          AS amountMinor,
                   quantity              AS quantity,
                   currency              AS currency,
                   policy_version        AS policyVersion,
                   expires_at            AS expiresAt,
                   created_at            AS createdAt,
                   updated_at            AS updatedAt
              FROM case_authorization
             WHERE case_id = #{caseId}
             ORDER BY created_at DESC, authorization_id DESC
             LIMIT 1
            """)
    StoredAuthorization findLatest(@Param("caseId") String caseId);

    @Select("""
            SELECT authorization_id      AS authorizationId,
                   case_id               AS caseId,
                   authorization_version AS authorizationVersion,
                   status                AS status,
                   action                AS action,
                   input_revision        AS inputRevision,
                   proposal_id           AS proposalId,
                   planned_operation_id  AS plannedOperationId,
                   payload_hash          AS payloadHash,
                   amount_minor          AS amountMinor,
                   quantity              AS quantity,
                   currency              AS currency,
                   policy_version        AS policyVersion,
                   expires_at            AS expiresAt,
                   created_at            AS createdAt,
                   updated_at            AS updatedAt
              FROM case_authorization
             WHERE authorization_id = #{authorizationId}
            """)
    StoredAuthorization findByAuthorizationId(@Param("authorizationId") String authorizationId);

    /** A stored authorisation row, exactly as the table holds it. */
    record StoredAuthorization(
            String authorizationId,
            String caseId,
            long authorizationVersion,
            String status,
            String action,
            int inputRevision,
            String proposalId,
            String plannedOperationId,
            String payloadHash,
            long amountMinor,
            int quantity,
            String currency,
            String policyVersion,
            Instant expiresAt,
            Instant createdAt,
            Instant updatedAt) {

        public AuthorizationStatus authorizationStatus() {
            return AuthorizationStatus.of(status);
        }
    }
}
