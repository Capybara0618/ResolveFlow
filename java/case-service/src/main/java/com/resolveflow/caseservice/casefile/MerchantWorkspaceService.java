package com.resolveflow.caseservice.casefile;

import com.resolveflow.caseservice.policy.PolicyController;
import com.resolveflow.caseservice.policy.PolicyRepository;
import com.resolveflow.shared.security.AuthenticatedPrincipal;
import com.resolveflow.shared.security.Role;
import java.time.Instant;
import java.util.ArrayList;
import java.util.List;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Isolation;
import org.springframework.transaction.annotation.Transactional;

/** Read-only merchant projections; authority: docs/merchant-workspace.md. */
@Service
public class MerchantWorkspaceService {
    private final JdbcTemplate jdbc;
    private final PolicyRepository policies;

    public MerchantWorkspaceService(JdbcTemplate jdbc, PolicyRepository policies) {
        this.jdbc = jdbc;
        this.policies = policies;
    }

    static void admin(AuthenticatedPrincipal principal) {
        if (principal.role() != Role.MERCHANT_ADMIN)
            throw new CaseService.ForbiddenScopeException("merchant administrator required");
    }

    public record Item(
            String case_id,
            String status,
            String description,
            String owner_name,
            String owner_username,
            Instant updated_at,
            List<String> reasons) {}

    public record Overview(
            long unclaimed,
            long mine,
            long attention,
            long enabled_staff,
            long coordination_total,
            List<Item> items,
            Instant observed_at) {}

    // Correlated EXISTS avoids multiplying a case by its callbacks, authorisations or proposals.
    private static final String FACTS = """
        SELECT c.case_id,c.status,c.description,c.updated_at,o.owner_username,a.display_name,
          (o.owner_username IS NULL AND c.status IN ('QUEUED','ANALYZING','WAITING_CUSTOMER','PENDING_REVIEW')
           AND NOT EXISTS(SELECT 1 FROM case_authorization z WHERE z.case_id=c.case_id AND z.status='CONSUMED')) AS unclaimed,
          (c.status='RECONCILING') AS unknown_result,
          (o.owner_username IS NOT NULL AND (a.username IS NULL OR a.enabled=FALSE
            OR a.role NOT IN ('REVIEWER','MERCHANT_ADMIN','OPERATOR'))) AS unavailable_owner,
          (EXISTS(SELECT 1 FROM agent_callback b WHERE b.case_id=c.case_id AND b.input_revision=c.input_revision
            AND b.kind='FAILED' AND b.disposition='ACCEPTED')
           AND NOT EXISTS(SELECT 1 FROM case_proposal p WHERE p.case_id=c.case_id AND p.input_revision=c.input_revision
             AND p.status='VALIDATED')) AS failed_investigation
        FROM aftersale_case c LEFT JOIN case_collaboration o ON o.case_id=c.case_id
        LEFT JOIN identity_account a ON a.username=o.owner_username AND a.merchant_id=c.merchant_id
        WHERE c.merchant_id=? AND c.status NOT IN ('CLOSED_SUCCESS','CLOSED_REJECTED','CANCELLED')
        """;

    @Transactional(readOnly = true, isolation = Isolation.REPEATABLE_READ)
    public Overview overview(AuthenticatedPrincipal principal) {
        admin(principal);
        var counts = jdbc.queryForMap(
                "SELECT COALESCE(SUM(unclaimed),0) unclaimed, COALESCE(SUM(owner_username=?),0) mine, "
                        + "COALESCE(SUM(unknown_result OR unavailable_owner OR failed_investigation),0) attention, "
                        + "COALESCE(SUM(unclaimed OR unknown_result OR unavailable_owner OR failed_investigation),0) coordination_total FROM ("
                        + FACTS + ") f",
                principal.subject(),
                principal.merchantId());
        var items = jdbc.query(
                "SELECT * FROM (" + FACTS
                        + ") f WHERE unclaimed OR unknown_result OR unavailable_owner OR failed_investigation "
                        + "ORDER BY (unknown_result OR unavailable_owner OR failed_investigation) DESC,updated_at,case_id LIMIT 20",
                (rs, n) -> {
                    List<String> reasons = new ArrayList<>();
                    if (rs.getBoolean("unclaimed")) reasons.add("UNCLAIMED");
                    if (rs.getBoolean("unknown_result")) reasons.add("RESULT_UNKNOWN");
                    if (rs.getBoolean("unavailable_owner")) reasons.add("OWNER_UNAVAILABLE");
                    if (rs.getBoolean("failed_investigation")) reasons.add("INVESTIGATION_FAILED");
                    return new Item(
                            rs.getString("case_id"),
                            rs.getString("status"),
                            rs.getString("description"),
                            rs.getString("display_name"),
                            rs.getString("owner_username"),
                            rs.getTimestamp("updated_at").toInstant(),
                            reasons);
                },
                principal.merchantId());
        long staff = jdbc.queryForObject(
                "SELECT COUNT(*) FROM identity_account WHERE merchant_id=? AND enabled=TRUE AND role IN ('REVIEWER','MERCHANT_ADMIN','OPERATOR')",
                Long.class,
                principal.merchantId());
        return new Overview(
                ((Number) counts.get("unclaimed")).longValue(),
                ((Number) counts.get("mine")).longValue(),
                ((Number) counts.get("attention")).longValue(),
                staff,
                ((Number) counts.get("coordination_total")).longValue(),
                items,
                Instant.now());
    }

    public record Policy(
            String bundle_id,
            String version,
            String manifest_hash,
            int safety_epoch,
            Instant effective_from,
            Instant effective_to,
            Instant imported_at,
            long rule_count) {}

    public record PolicyList(List<Policy> items, boolean truncated) {}

    public record Rule(String rule_id, String title, String text, String chunk_id, String content_hash) {}

    public record PolicyDetail(Policy policy, List<Rule> rules, Object index) {}

    private static final String POLICY = """
        SELECT b.bundle_id,b.version,b.manifest_hash,b.safety_epoch,b.effective_from,b.effective_to,b.imported_at,
          (SELECT COUNT(*) FROM policy_rule r WHERE r.bundle_id=b.bundle_id) AS rule_count
        FROM policy_bundle b WHERE b.merchant_id=?
        """;

    private static Policy policy(java.sql.ResultSet rs) throws java.sql.SQLException {
        return new Policy(
                rs.getString("bundle_id"),
                rs.getString("version"),
                rs.getString("manifest_hash"),
                rs.getInt("safety_epoch"),
                rs.getTimestamp("effective_from").toInstant(),
                rs.getTimestamp("effective_to") == null
                        ? null
                        : rs.getTimestamp("effective_to").toInstant(),
                rs.getTimestamp("imported_at").toInstant(),
                rs.getLong("rule_count"));
    }

    @Transactional(readOnly = true)
    public PolicyList list(AuthenticatedPrincipal principal) {
        admin(principal);
        var rows = jdbc.query(
                POLICY + " ORDER BY b.effective_from DESC,b.bundle_id LIMIT 101",
                (rs, n) -> policy(rs),
                principal.merchantId());
        return new PolicyList(rows.stream().limit(100).toList(), rows.size() > 100);
    }

    @Transactional(readOnly = true, isolation = Isolation.REPEATABLE_READ)
    public PolicyDetail detail(AuthenticatedPrincipal principal, String bundle) {
        admin(principal);
        var rows = jdbc.query(POLICY + " AND b.bundle_id=?", (rs, n) -> policy(rs), principal.merchantId(), bundle);
        if (rows.isEmpty()) throw new PolicyController.PolicyBundleNotFoundException();
        return new PolicyDetail(
                rows.get(0),
                policies.findRules(bundle).stream()
                        .map(r -> new Rule(r.ruleId(), r.title(), r.text(), r.chunkId(), r.contentHash()))
                        .toList(),
                null);
    }
}
