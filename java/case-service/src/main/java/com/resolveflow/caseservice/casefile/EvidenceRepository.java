package com.resolveflow.caseservice.casefile;

import java.util.List;
import org.apache.ibatis.annotations.Insert;
import org.apache.ibatis.annotations.Mapper;
import org.apache.ibatis.annotations.Param;
import org.apache.ibatis.annotations.Select;
import org.apache.ibatis.annotations.Update;

/**
 * Customer and reviewer material, appended only (docs/domain-model.md:27).
 *
 * <p>There is deliberately no update and no delete statement in this mapper. "Material is never
 * overwritten" is therefore not a rule somebody has to remember while writing a service: there is no
 * code path that could break it.
 */
@Mapper
public interface EvidenceRepository {

    @Insert("""
            INSERT INTO case_evidence (case_id, evidence_id, source_type, source_ref, source_version,
                                       content_hash, input_revision, observed_at, content, question_id,
                                       appended_by, appended_role, created_at)
            VALUES (#{caseId}, #{evidenceId}, #{sourceType}, #{sourceRef}, #{sourceVersion},
                    #{contentHash}, #{inputRevision}, #{observedAt}, #{content}, #{questionId},
                    #{appendedBy}, #{appendedRole}, #{createdAt})
            """)
    void insertEvidence(
            @Param("caseId") String caseId,
            @Param("evidenceId") String evidenceId,
            @Param("sourceType") String sourceType,
            @Param("sourceRef") String sourceRef,
            @Param("sourceVersion") String sourceVersion,
            @Param("contentHash") String contentHash,
            @Param("inputRevision") int inputRevision,
            @Param("observedAt") java.time.Instant observedAt,
            @Param("content") String content,
            @Param("questionId") String questionId,
            @Param("appendedBy") String appendedBy,
            @Param("appendedRole") String appendedRole,
            @Param("createdAt") java.time.Instant createdAt);

    /**
     * The material of a case, oldest first, capped by the caller.
     *
     * <p>Newest-first in the query and reversed by the caller, so a cap keeps the most recent material
     * rather than an arbitrary prefix of the oldest.
     */
    @Select("""
            SELECT case_id        AS caseId,
                   evidence_id    AS evidenceId,
                   source_type    AS sourceType,
                   source_ref     AS sourceRef,
                   source_version AS sourceVersion,
                   content_hash   AS contentHash,
                   input_revision AS inputRevision,
                   observed_at    AS observedAt,
                   content        AS content,
                   question_id    AS questionId,
                   appended_by    AS appendedBy,
                   appended_role  AS appendedRole,
                   created_at     AS createdAt
              FROM case_evidence
             WHERE case_id = #{caseId}
             ORDER BY input_revision DESC, created_at DESC, evidence_id DESC
             LIMIT #{limit}
            """)
    List<EvidenceRow> findRecent(@Param("caseId") String caseId, @Param("limit") int limit);

    @Select("""
            SELECT COUNT(*)
              FROM case_evidence
             WHERE case_id = #{caseId}
            """)
    int countForCase(@Param("caseId") String caseId);

    /**
     * Bump the case's input revision and its version together, under the row lock the caller holds.
     *
     * <p>Both move in one statement so a reader can never see a revision without the version that goes
     * with it. The status moves out of {@code WAITING_CUSTOMER} only: that is the documented edge
     * ({{@code 补证从 WAITING_CUSTOMER 增 revision→QUEUED}}, docs/domain-model.md:55), and material that
     * arrives while a proposal is under review bumps the revision without pretending the case went back
     * to the queue.
     */
    @Update("""
            UPDATE aftersale_case
               SET input_revision = input_revision + 1,
                   version = version + 1,
                   status = CASE WHEN status = 'WAITING_CUSTOMER' THEN 'QUEUED' ELSE status END,
                   updated_at = #{updatedAt}
             WHERE case_id = #{caseId}
            """)
    void bumpRevision(@Param("caseId") String caseId, @Param("updatedAt") java.time.Instant updatedAt);

    /** One appended record, as stored. */
    record EvidenceRow(
            String caseId,
            String evidenceId,
            String sourceType,
            String sourceRef,
            String sourceVersion,
            String contentHash,
            int inputRevision,
            java.time.Instant observedAt,
            String content,
            String questionId,
            String appendedBy,
            String appendedRole,
            java.time.Instant createdAt) {}
}
