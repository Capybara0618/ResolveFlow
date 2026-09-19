package com.resolveflow.caseservice.casefile;

import com.resolveflow.shared.contract.CanonicalJson;
import java.time.Instant;
import java.util.List;
import org.apache.ibatis.annotations.Insert;
import org.apache.ibatis.annotations.Mapper;
import org.apache.ibatis.annotations.Param;
import org.apache.ibatis.annotations.Select;
import tools.jackson.databind.JsonNode;
import tools.jackson.databind.ObjectMapper;

/**
 * The proposals of a case: the submitted document and what the re-check made of it.
 *
 * <p>Only inserts and reads, like the callback inbox: a proposal is a record of something that happened, and
 * the one member that changes meaning over time — whether it is still about the case's current revision — is
 * derived at read time instead of being rewritten here (C03.2b-2).
 */
@Mapper
public interface ProposalRepository {

    @Insert("""
            INSERT INTO case_proposal (proposal_id, case_id, run_id, input_revision, sequence, status,
                                       recomputed_amount_minor, refusal_reason, payload, payload_hash, created_at)
            VALUES (#{proposalId}, #{caseId}, #{runId}, #{inputRevision}, #{sequence}, #{status},
                    #{recomputedAmountMinor}, #{refusalReason}, #{payload}, #{payloadHash}, #{createdAt})
            """)
    void insert(
            @Param("proposalId") String proposalId,
            @Param("caseId") String caseId,
            @Param("runId") String runId,
            @Param("inputRevision") int inputRevision,
            @Param("sequence") long sequence,
            @Param("status") String status,
            @Param("recomputedAmountMinor") Long recomputedAmountMinor,
            @Param("refusalReason") String refusalReason,
            @Param("payload") String payload,
            @Param("payloadHash") String payloadHash,
            @Param("createdAt") Instant createdAt);

    /**
     * The next proposal number for a case.
     *
     * <p>Read inside the transaction that already holds the case's row lock, so two proposals cannot be
     * numbered the same; the unique key on (case_id, sequence) is what makes that a property of the schema
     * rather than of the order two statements happened to run in.
     */
    @Select("SELECT COALESCE(MAX(sequence), 0) + 1 FROM case_proposal WHERE case_id = #{caseId}")
    long nextSequence(@Param("caseId") String caseId);

    /** The proposal a reader should see: the latest one this case has. */
    @Select("""
            SELECT proposal_id             AS proposalId,
                   case_id                 AS caseId,
                   run_id                  AS runId,
                   input_revision          AS inputRevision,
                   sequence                AS sequence,
                   status                  AS status,
                   recomputed_amount_minor AS recomputedAmountMinor,
                   refusal_reason          AS refusalReason,
                   payload                 AS payload,
                   payload_hash            AS payloadHash,
                   created_at              AS createdAt
              FROM case_proposal
             WHERE case_id = #{caseId}
             ORDER BY sequence DESC
             LIMIT 1
            """)
    StoredProposal findLatest(@Param("caseId") String caseId);

    @Select("""
            SELECT proposal_id             AS proposalId,
                   case_id                 AS caseId,
                   run_id                  AS runId,
                   input_revision          AS inputRevision,
                   sequence                AS sequence,
                   status                  AS status,
                   recomputed_amount_minor AS recomputedAmountMinor,
                   refusal_reason          AS refusalReason,
                   payload                 AS payload,
                   payload_hash            AS payloadHash,
                   created_at              AS createdAt
              FROM case_proposal
             WHERE proposal_id = #{proposalId}
            """)
    StoredProposal findByProposalId(@Param("proposalId") String proposalId);

    /** Every proposal of a case in submission order; used by tests and by a reviewer reading the history. */
    @Select("""
            SELECT proposal_id             AS proposalId,
                   case_id                 AS caseId,
                   run_id                  AS runId,
                   input_revision          AS inputRevision,
                   sequence                AS sequence,
                   status                  AS status,
                   recomputed_amount_minor AS recomputedAmountMinor,
                   refusal_reason          AS refusalReason,
                   payload                 AS payload,
                   payload_hash            AS payloadHash,
                   created_at              AS createdAt
              FROM case_proposal
             WHERE case_id = #{caseId}
             ORDER BY sequence
            """)
    List<StoredProposal> findAll(@Param("caseId") String caseId);

    /** A stored proposal row, exactly as the table holds it. */
    record StoredProposal(
            String proposalId,
            String caseId,
            String runId,
            int inputRevision,
            long sequence,
            String status,
            Long recomputedAmountMinor,
            String refusalReason,
            String payload,
            String payloadHash,
            Instant createdAt) {

        public ProposalStatus proposalStatus() {
            return ProposalStatus.of(status);
        }

        /**
         * The status a reader should be shown: a proposal for a revision the case has moved past is stale.
         *
         * <p>Derived rather than stored, so it cannot be forgotten when a revision moves, and derived from the
         * case's revision rather than from a clock, so two readers of the same state see the same answer.
         */
        public ProposalStatus statusAt(int caseInputRevision) {
            return inputRevision < caseInputRevision ? ProposalStatus.STALE : proposalStatus();
        }

        public JsonNode payloadAsJson(ObjectMapper mapper) {
            return mapper.readTree(payload);
        }

        /** The hash of the stored document, recomputed so a row edited underneath this service is caught. */
        public String contentHash(ObjectMapper mapper) {
            return CanonicalJson.contentHash(payloadAsJson(mapper));
        }
    }
}
