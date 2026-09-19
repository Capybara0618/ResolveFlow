package com.resolveflow.caseservice.policy;

import java.time.Instant;
import java.util.List;
import org.apache.ibatis.annotations.Insert;
import org.apache.ibatis.annotations.Mapper;
import org.apache.ibatis.annotations.Param;
import org.apache.ibatis.annotations.Select;

/**
 * The policy a case is pinned to.
 *
 * <p>Whichever way a case is opened, it happens inside one transaction with the case itself: a case exists
 * with a policy manifest or it does not exist. That is why there is no "update the manifest" statement here
 * — re-pinning a case to a newer policy is precisely the silent switch docs/core-contracts.md:50 forbids.
 */
@Mapper
public interface PolicyManifestRepository {

    @Insert("""
            INSERT INTO case_policy_manifest (case_id, manifest_hash, safety_epoch, effective_from,
                                              effective_to, selected_by_paid_at, pinned_at)
            VALUES (#{caseId}, #{manifestHash}, #{safetyEpoch}, #{effectiveFrom}, #{effectiveTo},
                    #{selectedByPaidAt}, #{pinnedAt})
            """)
    void insertManifest(
            @Param("caseId") String caseId,
            @Param("manifestHash") String manifestHash,
            @Param("safetyEpoch") int safetyEpoch,
            @Param("effectiveFrom") Instant effectiveFrom,
            @Param("effectiveTo") Instant effectiveTo,
            @Param("selectedByPaidAt") Instant selectedByPaidAt,
            @Param("pinnedAt") Instant pinnedAt);

    @Insert("""
            INSERT INTO case_policy_bundle (case_id, bundle_id)
            VALUES (#{caseId}, #{bundleId})
            """)
    void insertBundle(@Param("caseId") String caseId, @Param("bundleId") String bundleId);

    @Select("""
            SELECT manifest_hash       AS manifestHash,
                   safety_epoch        AS safetyEpoch,
                   effective_from      AS effectiveFrom,
                   effective_to        AS effectiveTo,
                   selected_by_paid_at AS selectedByPaidAt
              FROM case_policy_manifest
             WHERE case_id = #{caseId}
            """)
    StoredManifest findManifest(@Param("caseId") String caseId);

    /** The bundle ids of a pinned manifest, in the order the case recorded them. */
    @Select("""
            SELECT bundle_id
              FROM case_policy_bundle
             WHERE case_id = #{caseId}
             ORDER BY bundle_id
            """)
    List<String> findBundleIds(@Param("caseId") String caseId);

    /** A pinned manifest without its bundle ids. */
    record StoredManifest(
            String manifestHash,
            int safetyEpoch,
            Instant effectiveFrom,
            Instant effectiveTo,
            Instant selectedByPaidAt) {}
}
