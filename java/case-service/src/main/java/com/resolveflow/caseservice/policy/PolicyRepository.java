package com.resolveflow.caseservice.policy;

import java.time.Instant;
import java.util.List;
import org.apache.ibatis.annotations.Insert;
import org.apache.ibatis.annotations.Mapper;
import org.apache.ibatis.annotations.Param;
import org.apache.ibatis.annotations.Select;

/**
 * Stored policy bundles and their rules.
 *
 * <p>There is deliberately no update and no delete statement here. A version is immutable, and the way to
 * be sure of that is for the code to have no means of editing one — the migration's triggers refuse an edit
 * as well, but they are the second line, not the first.
 */
@Mapper
public interface PolicyRepository {

    @Insert("""
            INSERT INTO policy_bundle (bundle_id, version, manifest_hash, safety_epoch, effective_from,
                                       effective_to, imported_at, source_path)
            VALUES (#{bundleId}, #{version}, #{manifestHash}, #{safetyEpoch}, #{effectiveFrom},
                    #{effectiveTo}, #{importedAt}, #{sourcePath})
            """)
    void insertBundle(
            @Param("bundleId") String bundleId,
            @Param("version") String version,
            @Param("manifestHash") String manifestHash,
            @Param("safetyEpoch") int safetyEpoch,
            @Param("effectiveFrom") Instant effectiveFrom,
            @Param("effectiveTo") Instant effectiveTo,
            @Param("importedAt") Instant importedAt,
            @Param("sourcePath") String sourcePath);

    @Insert("""
            INSERT INTO policy_rule (bundle_id, rule_id, position, title, text)
            VALUES (#{bundleId}, #{ruleId}, #{position}, #{title}, #{text})
            """)
    void insertRule(
            @Param("bundleId") String bundleId,
            @Param("ruleId") String ruleId,
            @Param("position") int position,
            @Param("title") String title,
            @Param("text") String text);

    @Select("""
            SELECT bundle_id      AS bundleId,
                   version        AS version,
                   manifest_hash  AS manifestHash,
                   safety_epoch   AS safetyEpoch,
                   effective_from AS effectiveFrom,
                   effective_to   AS effectiveTo
              FROM policy_bundle
             WHERE bundle_id = #{bundleId}
            """)
    StoredBundle findBundle(@Param("bundleId") String bundleId);

    /**
     * Rules in the order the source file wrote them, as rows: position included, chunk id and content hash not.
     *
     * <p>{@link #findRules(String)} derives the citable members from the row, so what this returns is what was
     * actually imported. Storing them instead would let a stored hash outlive an edit to the text it describes.
     */
    @Select("""
            SELECT bundle_id AS bundleId,
                   position   AS position,
                   rule_id    AS ruleId,
                   title      AS title,
                   text       AS text
              FROM policy_rule
             WHERE bundle_id = #{bundleId}
             ORDER BY position
            """)
    List<StoredRule> findStoredRules(@Param("bundleId") String bundleId);

    /** The citable rules of a bundle, with their chunk ids and hashes derived from the stored text. */
    default List<PolicyRule> findRules(String bundleId) {
        return findStoredRules(bundleId).stream()
                .map(row -> PolicyRule.from(row.bundleId(), row.position(), row.ruleId(), row.title(), row.text()))
                .toList();
    }

    /**
     * Every stored window, locked, so an import can refuse one that would overlap an existing version.
     *
     * <p>{@code FOR UPDATE} is what makes the refusal hold: the answer decides whether the caller inserts,
     * and two imports running at once must not both find the range free. It is only ever called inside the
     * import transaction.
     */
    @Select("""
            SELECT bundle_id      AS bundleId,
                   manifest_hash  AS manifestHash,
                   safety_epoch   AS safetyEpoch,
                   effective_from AS effectiveFrom,
                   effective_to   AS effectiveTo
              FROM policy_bundle
             ORDER BY effective_from
               FOR UPDATE
            """)
    List<StoredWindow> listWindowsForUpdate();

    /**
     * The installed windows, read without a lock, for choosing a version by payment time.
     *
     * <p>{@link #listWindowsForUpdate()} is the same query on purpose: that one is a locking read inside
     * the import transaction, where the answer decides whether an insert happens, and this one is an
     * ordinary read where the answer decides which version a case is pinned to. Making them one method
     * would put a lock on the case-opening path for no reason.
     */
    @Select("""
            SELECT bundle_id      AS bundleId,
                   manifest_hash  AS manifestHash,
                   safety_epoch   AS safetyEpoch,
                   effective_from AS effectiveFrom,
                   effective_to   AS effectiveTo
              FROM policy_bundle
             ORDER BY effective_from
            """)
    List<StoredWindow> listEffectiveWindows();

    /** A stored rule row, exactly as {@code policy_rule} holds it. */
    record StoredRule(String bundleId, int position, String ruleId, String title, String text) {}

    /** A stored bundle header, without its rules. */
    record StoredBundle(
            String bundleId,
            String version,
            String manifestHash,
            int safetyEpoch,
            Instant effectiveFrom,
            Instant effectiveTo) {}

    /** A stored window, used for overlap checks and for choosing a version. */
    record StoredWindow(
            String bundleId, String manifestHash, int safetyEpoch, Instant effectiveFrom, Instant effectiveTo) {}
}
