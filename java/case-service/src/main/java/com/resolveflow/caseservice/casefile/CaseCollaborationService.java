package com.resolveflow.caseservice.casefile;

import com.fasterxml.jackson.annotation.JsonProperty;
import com.resolveflow.caseservice.order.RequestPrincipalResolver;
import com.resolveflow.shared.security.AuthenticatedPrincipal;
import com.resolveflow.shared.security.Role;
import java.time.Clock;
import java.time.Instant;
import java.util.List;
import java.util.Objects;
import java.util.TreeSet;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

/** Case lock -> merchant shared lock -> sorted account shared locks; assignment has no business writes. */
@Service
public class CaseCollaborationService {
    private final CaseRepository cases;
    private final AuthorizationRepository authorizations;
    private final JdbcTemplate jdbc;
    private final Clock clock;

    public CaseCollaborationService(
            CaseRepository cases, AuthorizationRepository authorizations, JdbcTemplate jdbc, Clock clock) {
        this.cases = cases;
        this.authorizations = authorizations;
        this.jdbc = jdbc;
        this.clock = clock;
    }

    public record Owner(
            String username, @JsonProperty("display_name") String displayName, Role role, boolean enabled) {}

    public record Event(
            long version,
            String action,
            @JsonProperty("actor_username") String actorUsername,
            @JsonProperty("from_username") String fromUsername,
            @JsonProperty("to_username") String toUsername,
            String reason,
            @JsonProperty("occurred_at") Instant occurredAt) {}

    public record View(
            @JsonProperty("case_id") String caseId,
            long version,
            Owner owner,
            @JsonProperty("is_owner") boolean isOwner,
            @JsonProperty("allowed_actions") List<String> allowedActions,
            List<Event> history) {}

    public record Action(
            String action, @JsonProperty("target_username") String targetUsername, String reason) {}

    private record Assignment(String owner, long version) {}

    private boolean singleOperator(String merchantId) {
        var modes = jdbc.queryForList(
                "SELECT single_operator FROM identity_merchant WHERE merchant_id=?", Boolean.class, merchantId);
        return !modes.isEmpty() && Boolean.TRUE.equals(modes.getFirst());
    }

    /** Part of case creation: case row -> merchant -> account locks, without a network call. */
    public void initializeMerchantOwner(String caseId, String merchantId, Instant now) {
        if (!org.springframework.transaction.support.TransactionSynchronizationManager.isActualTransactionActive())
            throw new IllegalStateException("automatic assignment requires the case creation transaction");
        var modes = jdbc.query(
                "SELECT single_operator,enabled FROM identity_merchant WHERE merchant_id=? FOR SHARE",
                (rs, n) -> {
                    if (rs.getBoolean(1) && !rs.getBoolean(2))
                        throw new CaseService.ForbiddenScopeException("本店已停用，不能创建新的售后申请");
                    return rs.getBoolean(1);
                },
                merchantId);
        if (modes.isEmpty() || !Boolean.TRUE.equals(modes.getFirst())) return;
        var owners = jdbc.queryForList(
                "SELECT username FROM identity_account WHERE merchant_id=? AND role='MERCHANT_ADMIN' AND enabled=TRUE ORDER BY username FOR SHARE",
                String.class,
                merchantId);
        if (owners.size() != 1) throw conflict("本店商家账号尚未准备好，请联系平台管理员");
        String owner = owners.getFirst();
        jdbc.update(
                "INSERT INTO case_collaboration(case_id,owner_username,version,updated_at) VALUES (?,?,1,?)",
                caseId,
                owner,
                java.sql.Timestamp.from(now));
        jdbc.update(
                "INSERT INTO case_collaboration_event(case_id,version,action,actor_username,to_username,reason,occurred_at) VALUES (?,1,'AUTO_ASSIGN','SYSTEM',?,'新申请自动归属本店商家',?)",
                caseId,
                owner,
                java.sql.Timestamp.from(now));
    }

    private record Account(String merchant, Role role, String customer, boolean enabled, long version) {}

    public record WritePermit(long identityVersion, String caseMatch, String collaborationMatch) {
        public static WritePermit from(
                RequestPrincipalResolver.Session session, String caseMatch, String collaborationMatch) {
            return new WritePermit(session.identityVersion(), caseMatch, collaborationMatch);
        }
    }

    /** An optimistic preflight for network checks; authoritative validation is repeated under the case lock. */
    public CaseRow prepareWrite(AuthenticatedPrincipal principal, String caseId, WritePermit permit) {
        CaseStaff.requireReviewer(principal, "人工操作需要本商家工作人员身份");
        CaseRow row = visible(principal, cases.findCase(caseId));
        requireOwnReading(principal, row, permit);
        return row;
    }

    public void requireOwner(AuthenticatedPrincipal principal, CaseRow lockedRow, WritePermit permit) {
        if (!org.springframework.transaction.support.TransactionSynchronizationManager.isActualTransactionActive())
            throw new IllegalStateException("owner validation requires the case write transaction");
        requireOwnReading(principal, lockedRow, permit);
        lockCurrentIdentity(principal, permit.identityVersion(), null);
    }

    @Transactional(noRollbackFor = ReviewDecisionService.AuthorizationLapsedException.class)
    public <T> T writeOwned(
            AuthenticatedPrincipal principal,
            String caseId,
            WritePermit permit,
            java.util.function.Function<CaseRow, T> command) {
        CaseRow row = visible(principal, cases.findCaseForUpdate(caseId));
        requireOwner(principal, row, permit);
        return command.apply(row);
    }

    public boolean owns(AuthenticatedPrincipal principal, String caseId) {
        return principal.subject().equals(assignment(caseId).owner());
    }

    private void requireOwnReading(AuthenticatedPrincipal principal, CaseRow row, WritePermit permit) {
        CaseStaff.requireReviewer(principal, "人工操作需要工作人员身份");
        if (row.status().isTerminal() || authorizations.hasConsumed(row.caseId()))
            throw conflict("工单状态为 " + row.status() + "；已结束或授权已消费，人工输入已冻结");
        if (permit == null || permit.collaborationMatch() == null) throw conflict("请先领取工单并刷新协作版本");
        Assignment current = assignment(row.caseId());
        long expected = version(permit.collaborationMatch());
        if (current.version() != expected || !principal.subject().equals(current.owner()))
            throw conflict("工单负责人已变化或尚未领取，请刷新后操作");
        if (permit.caseMatch() == null) throw conflict("缺少工单版本，请刷新后操作");
        if (!permit.caseMatch().matches("\"[1-9][0-9]{0,15}\"")) throw invalid("If-Match需要带引号的工单版本");
        if (Long.parseLong(permit.caseMatch().substring(1, permit.caseMatch().length() - 1)) != row.version())
            throw conflict("工单已更新，请重新核对材料后提交");
    }

    @Transactional(readOnly = true)
    public View read(AuthenticatedPrincipal principal, String caseId) {
        CaseStaff.require(principal, "协作信息仅向本商家工作人员开放");
        CaseRow row = visible(principal, cases.findCase(caseId));
        return view(principal, row, assignment(caseId));
    }

    @Transactional
    public View act(
            AuthenticatedPrincipal principal, long identityVersion, String caseId, String ifMatch, Action request) {
        CaseStaff.require(principal, "协作操作需要工作人员身份");
        CaseRow row = visible(principal, cases.findCaseForUpdate(caseId));
        boolean admin = principal.role() == Role.MERCHANT_ADMIN;
        if (!List.of("CLAIM", "RELEASE", "TRANSFER", "TAKEOVER").contains(Objects.toString(request.action(), "")))
            throw invalid("不支持的协作操作");
        if ("TAKEOVER".equals(request.action()) && !admin)
            throw new CaseService.ForbiddenScopeException("只有商家管理员可以显式接管");
        if (ifMatch == null) throw conflict("缺少协作版本，请刷新后领取或操作");
        long expected = version(ifMatch);
        if (!assignable(row)) throw conflict("已批准、执行中或已结束的工单不能更改负责人");
        String reason = request.reason();
        if (reason == null || reason.isBlank() || reason.length() > 1000) throw invalid("请填写1–1000字的操作理由");
        String target = "TRANSFER".equals(request.action()) ? request.targetUsername() : null;
        if ("TRANSFER".equals(request.action()) && (target == null || target.isBlank() || target.length() > 120))
            throw invalid("请选择本商家启用的工作人员");
        if (target != null) target = target.trim();
        else if (request.targetUsername() != null) throw invalid("该操作不接受转交目标");
        lockCurrentIdentity(principal, identityVersion, target);
        if (singleOperator(row.merchantId())) throw new CaseService.ForbiddenScopeException("本店由商家账号直接处理，不提供领取或转交");
        Assignment current = assignment(caseId);
        if ("CLAIM".equals(request.action()) && principal.subject().equals(current.owner()))
            return view(principal, row, current);
        if (current.version() != expected) throw conflict("负责人已变化，请刷新后重新操作");
        String next;
        switch (request.action()) {
            case "CLAIM" -> {
                if (current.owner() != null) throw conflict("工单已有负责人，请使用转交或管理员接管");
                next = principal.subject();
            }
            case "TAKEOVER" -> {
                if (principal.subject().equals(current.owner())) throw conflict("你已经是当前负责人");
                next = principal.subject();
            }
            default -> {
                if (current.owner() == null) throw conflict("工单尚未领取");
                if (!admin && !principal.subject().equals(current.owner())) throw conflict("只有当前负责人或管理员可以释放、转交");
                next = "RELEASE".equals(request.action()) ? null : target;
                if (Objects.equals(current.owner(), next)) throw invalid("转交目标已经是负责人");
            }
        }
        Instant now = Instant.now(clock);
        long nextVersion = current.version() + 1;
        if (current.version() == 0) {
            jdbc.update(
                    "INSERT INTO case_collaboration (case_id,owner_username,version,updated_at) VALUES (?,?,?,?)",
                    caseId,
                    next,
                    nextVersion,
                    java.sql.Timestamp.from(now));
        } else {
            jdbc.update(
                    "UPDATE case_collaboration SET owner_username=?,version=?,updated_at=? WHERE case_id=?",
                    next,
                    nextVersion,
                    java.sql.Timestamp.from(now),
                    caseId);
        }
        jdbc.update(
                """
                INSERT INTO case_collaboration_event
                    (case_id,version,action,actor_username,from_username,to_username,reason,occurred_at)
                VALUES (?,?,?,?,?,?,?,?)
                """,
                caseId,
                nextVersion,
                request.action(),
                principal.subject(),
                current.owner(),
                next,
                reason.trim(),
                java.sql.Timestamp.from(now));
        return view(principal, row, new Assignment(next, nextVersion));
    }

    /** Called only with the case row locked. Account locks also fence concurrent disable/reset/role changes. */
    private void lockCurrentIdentity(AuthenticatedPrincipal principal, long identityVersion, String target) {
        var merchants = jdbc.query(
                "SELECT enabled FROM identity_merchant WHERE merchant_id=? FOR SHARE",
                (rs, n) -> rs.getBoolean(1),
                principal.merchantId());
        if (merchants.isEmpty() || !merchants.getFirst()) throw inactive();
        var names = new TreeSet<String>();
        names.add(principal.subject());
        if (target != null) names.add(target);
        for (String name : names) {
            var accounts = jdbc.query(
                    """
                    SELECT merchant_id,role,buyer_id,enabled,identity_version FROM identity_account
                     WHERE username=? FOR SHARE
                    """,
                    (rs, n) -> new Account(
                            rs.getString(1),
                            Role.valueOf(rs.getString(2)),
                            rs.getString(3),
                            rs.getBoolean(4),
                            rs.getLong(5)),
                    name);
            Account account = accounts.isEmpty() ? null : accounts.getFirst();
            if (name.equals(principal.subject())) {
                if (account == null
                        || !account.enabled()
                        || account.version() != identityVersion
                        || !principal.merchantId().equals(account.merchant())
                        || principal.role() != account.role()
                        || !Objects.equals(principal.buyerId(), account.customer())) throw inactive();
            } else if (account == null
                    || !account.enabled()
                    || !principal.merchantId().equals(account.merchant())
                    || !account.role().isMerchantStaff()) throw invalid("请选择本商家启用的工作人员");
        }
    }

    private Assignment assignment(String caseId) {
        var found = jdbc.query(
                "SELECT owner_username,version FROM case_collaboration WHERE case_id=?",
                (rs, n) -> new Assignment(rs.getString(1), rs.getLong(2)),
                caseId);
        return found.isEmpty() ? new Assignment(null, 0) : found.getFirst();
    }

    private View view(AuthenticatedPrincipal principal, CaseRow row, Assignment assignment) {
        Owner owner = null;
        if (assignment.owner() != null) {
            owner = jdbc.queryForObject(
                    """
                    SELECT username,display_name,role,enabled FROM identity_account WHERE username=?
                    """,
                    (rs, n) -> new Owner(
                            rs.getString(1), rs.getString(2), Role.valueOf(rs.getString(3)), rs.getBoolean(4)),
                    assignment.owner());
        }
        List<String> actions = List.of();
        if (assignable(row) && !singleOperator(row.merchantId())) {
            boolean admin = principal.role() == Role.MERCHANT_ADMIN;
            if (owner == null) actions = admin ? List.of("CLAIM", "TAKEOVER") : List.of("CLAIM");
            else if (owner.username().equals(principal.subject())) actions = List.of("RELEASE", "TRANSFER");
            else if (admin) actions = List.of("RELEASE", "TRANSFER", "TAKEOVER");
        }
        var history = jdbc.query(
                """
                SELECT version,action,actor_username,from_username,to_username,reason,occurred_at
                  FROM case_collaboration_event WHERE case_id=? ORDER BY version
                """,
                (rs, n) -> new Event(
                        rs.getLong(1),
                        rs.getString(2),
                        rs.getString(3),
                        rs.getString(4),
                        rs.getString(5),
                        rs.getString(6),
                        rs.getTimestamp(7).toInstant()),
                row.caseId());
        return new View(
                row.caseId(),
                assignment.version(),
                owner,
                principal.subject().equals(assignment.owner()),
                actions,
                history);
    }

    public List<Owner> staff(AuthenticatedPrincipal principal) {
        CaseStaff.require(principal, "工作人员列表仅向本商家工作人员开放");
        return jdbc.query(
                """
                SELECT username,display_name,role,enabled FROM identity_account
                 WHERE merchant_id=? AND enabled=TRUE AND role IN ('REVIEWER','MERCHANT_ADMIN','OPERATOR')
                 ORDER BY display_name,username
                """,
                (rs, n) -> new Owner(rs.getString(1), rs.getString(2), Role.valueOf(rs.getString(3)), rs.getBoolean(4)),
                principal.merchantId());
    }

    private boolean assignable(CaseRow row) {
        return row.status().acceptsNewInput()
                && row.status() != CaseStatus.AUTHORIZED
                && !authorizations.hasConsumed(row.caseId());
    }

    private static long version(String value) {
        if (!value.matches("\"(?:0|[1-9][0-9]{0,14})\"")) throw invalid("If-Collaboration-Match需要带引号的协作版本");
        return Long.parseLong(value.substring(1, value.length() - 1));
    }

    private static CaseRow visible(AuthenticatedPrincipal principal, CaseRow row) {
        if (row == null || !row.visibleTo(principal)) throw new CaseReadService.CaseNotVisibleException();
        return row;
    }

    private static CaseService.SemanticInvalidException invalid(String message) {
        return new CaseService.SemanticInvalidException(message);
    }

    private static CaseStateConflictException conflict(String message) {
        return new CaseStateConflictException(message);
    }

    private static RequestPrincipalResolver.UnauthenticatedException inactive() {
        return new RequestPrincipalResolver.UnauthenticatedException("账号状态已变化，请重新登录");
    }
}
