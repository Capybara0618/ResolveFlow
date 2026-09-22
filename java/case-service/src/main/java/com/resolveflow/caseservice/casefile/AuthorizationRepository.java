package com.resolveflow.caseservice.casefile;

import java.time.Instant;
import org.apache.ibatis.annotations.Insert;
import org.apache.ibatis.annotations.Mapper;
import org.apache.ibatis.annotations.Param;
import org.apache.ibatis.annotations.Select;
import org.apache.ibatis.annotations.Update;

/**
 * The authorisation a human decides on (C03.3a).
 *
 * <p>Like the proposal table, this one is inserted in the transaction that produced it and is not rewritten
 * on read. What differs is that an authorisation <em>does</em> change after creation — it gets decided and
 * then consumed — so the transitions are here as explicit statements with the version bumping in the same
 * statement. There is no general update: the lifecycle's transitions are the whole set
 * (docs/domain-model.md:55,57), and a generic "save" would make a fourth state change possible without
 * anyone deciding it should be.
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
                   decided_by            AS decidedBy,
                   decided_role          AS decidedRole,
                   decided_at            AS decidedAt,
                   decision_reason       AS decisionReason,
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
                   decided_by            AS decidedBy,
                   decided_role          AS decidedRole,
                   decided_at            AS decidedAt,
                   decision_reason       AS decisionReason,
                   created_at            AS createdAt,
                   updated_at            AS updatedAt
              FROM case_authorization
             WHERE authorization_id = #{authorizationId}
            """)
    StoredAuthorization findByAuthorizationId(@Param("authorizationId") String authorizationId);

    /**
     * Record one human decision, and only if the row is still the version the reviewer saw.
     *
     * <p>The version and the waiting status are part of the UPDATE rather than a check before it, so two
     * reviewers deciding at once cannot both win: the second statement matches no row and reports zero
     * (docs/domain-model.md:31, "授权终局决定唯一"). The version moves with the status, which is what makes
     * the number the reviewer sent back a lock on the decision it was made from.
     */
    @Update("""
            UPDATE case_authorization
               SET status = #{status},
                   authorization_version = authorization_version + 1,
                   decided_by = #{decidedBy},
                   decided_role = #{decidedRole},
                   decided_at = #{decidedAt},
                   decision_reason = #{reason},
                   updated_at = #{decidedAt}
             WHERE authorization_id = #{authorizationId}
               AND authorization_version = #{expectedVersion}
               AND status = 'PENDING_REVIEW'
            """)
    int decide(
            @Param("authorizationId") String authorizationId,
            @Param("expectedVersion") long expectedVersion,
            @Param("status") String status,
            @Param("decidedBy") String decidedBy,
            @Param("decidedRole") String decidedRole,
            @Param("reason") String reason,
            @Param("decidedAt") Instant decidedAt);

    /**
     * Lapse an authorisation that can no longer be applied, with nobody having decided it.
     *
     * <p>Used when approval finds that the input it fixed has moved on: the authorisation is not refused on
     * its merits, so it is not REJECTED, but it can never be applied either. The reason is stored because
     * "why did this lapse" is the question the next reader has.
     */
    @Update("""
            UPDATE case_authorization
               SET status = 'EXPIRED',
                   authorization_version = authorization_version + 1,
                   decision_reason = #{reason},
                   updated_at = #{now}
             WHERE authorization_id = #{authorizationId}
               AND authorization_version = #{expectedVersion}
               AND status IN ('PENDING_REVIEW', 'APPROVED')
            """)
    int lapse(
            @Param("authorizationId") String authorizationId,
            @Param("expectedVersion") long expectedVersion,
            @Param("reason") String reason,
            @Param("now") Instant now);

    /**
     * Withdraw the authorisation a case still has alive, because a newer revision replaced it (C03.3c).
     *
     * <p>The live one is whichever row the unique key allows ({@code uq_authorization_live}), so this
     * statement does not need to be told its id — but the caller does, to name it in the trajectory, which is
     * why it reads first and names the id here as well. The version moves with the status, so a decision that
     * was in flight against the old version loses rather than applying to a withdrawn authorisation.
     *
     * <p>REVOKED rather than EXPIRED because somebody's act retired it (a newer proposal, or a material
     * change), and the reason records which act — this overwrites whatever reason the row carried, because the
     * row states the authorisation's current condition and the trajectory is where its history lives (the
     * decision that approved it is an {@code AUTHORIZATION_DECIDED} row naming this id). An authorisation that
     * was never decided keeps its null decision columns, so a withdrawal cannot be mistaken for a decision.
     */
    @Update("""
            UPDATE case_authorization
               SET status = 'REVOKED',
                   authorization_version = authorization_version + 1,
                   decision_reason = #{reason},
                   updated_at = #{now}
             WHERE authorization_id = #{authorizationId}
               AND authorization_version = #{expectedVersion}
               AND status IN ('PENDING_REVIEW', 'APPROVED')
            """)
    int revoke(
            @Param("authorizationId") String authorizationId,
            @Param("expectedVersion") long expectedVersion,
            @Param("reason") String reason,
            @Param("now") Instant now);

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
            String decidedBy,
            String decidedRole,
            Instant decidedAt,
            String decisionReason,
            Instant createdAt,
            Instant updatedAt) {

        public AuthorizationStatus authorizationStatus() {
            return AuthorizationStatus.of(status);
        }
    }
}
