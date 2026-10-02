package com.resolveflow.caseservice.auth;

import com.fasterxml.jackson.annotation.JsonInclude;
import com.fasterxml.jackson.annotation.JsonProperty;
import com.resolveflow.caseservice.casefile.CaseService;
import com.resolveflow.caseservice.casefile.CaseStateConflictException;
import com.resolveflow.caseservice.casefile.ReviewQueueService.InvalidPageException;
import com.resolveflow.caseservice.order.RequestPrincipalResolver;
import com.resolveflow.caseservice.order.RequestPrincipalResolver.Session;
import com.resolveflow.shared.security.DemoAccounts;
import com.resolveflow.shared.security.Role;
import java.nio.charset.StandardCharsets;
import java.security.SecureRandom;
import java.time.Instant;
import java.util.ArrayList;
import java.util.Base64;
import java.util.List;
import java.util.Map;
import java.util.TreeSet;
import org.springframework.dao.DuplicateKeyException;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Service;
import org.springframework.transaction.PlatformTransactionManager;
import org.springframework.transaction.annotation.Isolation;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.transaction.support.TransactionTemplate;
import tools.jackson.databind.ObjectMapper;

/** Merchant -> sorted account locks; never acquires a case lock or calls a business/Agent write. */
@Service
public class StaffAdminService {
    private final JdbcTemplate jdbc;
    private final TransactionTemplate writes;
    private final ObjectMapper json = new ObjectMapper();
    private static final SecureRandom RANDOM = new SecureRandom();

    public StaffAdminService(JdbcTemplate jdbc, PlatformTransactionManager transactions) {
        this.jdbc = jdbc;
        this.writes = new TransactionTemplate(transactions);
    }

    public record Account(
            String username,
            @JsonProperty("display_name") String displayName,
            Role role,
            boolean enabled,
            long version,
            @JsonProperty("created_at") Instant createdAt,
            @JsonProperty("updated_at") Instant updatedAt) {}

    public record Mutation(
            Account account,
            @JsonProperty("session_invalidated") boolean sessionInvalidated) {}

    @JsonInclude(JsonInclude.Include.NON_NULL)
    public record PageMeta(
            int limit, @JsonProperty("next_cursor") String nextCursor) {}

    public record Page(
            List<Account> items,
            PageMeta page,
            long total,
            @JsonProperty("enabled_admins") long enabledAdmins,
            @JsonProperty("current_username") String currentUsername) {}

    public record Create(
            String username,
            @JsonProperty("display_name") String displayName,
            String role,
            String password,
            String reason) {
        @Override
        public String toString() {
            return "Create[credentials redacted]";
        }
    }

    public record Update(
            @JsonProperty("display_name") String displayName, String role, Boolean enabled, String reason) {}

    public record Password(String password, String reason) {
        @Override
        public String toString() {
            return "Password[redacted]";
        }
    }

    public record Audit(
            String id,
            String action,
            @JsonProperty("actor_username") String actorUsername,
            @JsonProperty("account_version") long accountVersion,
            String reason,
            @JsonProperty("occurred_at") Instant occurredAt,
            Map<String, Object> before,
            Map<String, Object> after) {}

    public record AuditPage(List<Audit> items, PageMeta page, long total) {}

    public static class AccountNotVisibleException extends RuntimeException {
        public AccountNotVisibleException() {
            super("该账号不存在或不属于当前商家");
        }
    }

    private void requireAdmin(Session session) {
        if (session.principal().role() != Role.MERCHANT_ADMIN)
            throw new CaseService.ForbiddenScopeException("仅本商家管理员可维护账号");
    }

    private Account scoped(Session session, String username, boolean lock) {
        var rows = jdbc.query(
                "SELECT username,display_name,role,enabled,account_version,created_at,updated_at FROM identity_account WHERE merchant_id=? AND username=?"
                        + (lock ? " FOR UPDATE" : ""),
                (rs, n) -> new Account(
                        rs.getString(1),
                        rs.getString(2),
                        Role.valueOf(rs.getString(3)),
                        rs.getBoolean(4),
                        rs.getLong(5),
                        rs.getTimestamp(6).toInstant(),
                        rs.getTimestamp(7).toInstant()),
                session.principal().merchantId(),
                username);
        return rows.isEmpty() ? null : rows.getFirst();
    }

    private Account visible(Session session, String username) {
        Account row = scoped(session, username, false);
        if (row == null) throw new AccountNotVisibleException();
        return row;
    }

    private Account lockCurrent(Session session, String target) {
        var merchants = jdbc.query(
                "SELECT enabled FROM identity_merchant WHERE merchant_id=? FOR UPDATE",
                (rs, n) -> rs.getBoolean(1),
                session.principal().merchantId());
        if (merchants.isEmpty() || !merchants.getFirst()) throw inactive();
        Account selected = target == null ? null : visible(session, target);
        TreeSet<String> names = new TreeSet<>();
        names.add(session.principal().subject());
        if (selected != null) names.add(selected.username());
        Account current = null;
        for (String name : names) {
            Account locked = scoped(session, name, true);
            if (selected != null && selected.username().equals(name)) current = locked;
        }
        // Locking reads see the current committed row, not the earlier RR visibility snapshot.
        var actors = jdbc.query(
                "SELECT identity_version,role,enabled,customer_id FROM identity_account WHERE merchant_id=? AND username=? FOR UPDATE",
                (rs, n) -> rs.getLong(1) == session.identityVersion()
                        && rs.getString(2).equals(session.principal().role().name())
                        && rs.getBoolean(3)
                        && java.util.Objects.equals(
                                rs.getString(4), session.principal().customerId()),
                session.principal().merchantId(),
                session.principal().subject());
        if (actors.isEmpty() || !actors.getFirst()) throw inactive();
        if (selected != null && current == null) throw new AccountNotVisibleException();
        return current;
    }

    private static RequestPrincipalResolver.UnauthenticatedException inactive() {
        return new RequestPrincipalResolver.UnauthenticatedException("账号状态或权限已变化，请重新登录");
    }

    private long enabledAdmins(Session session) {
        return jdbc.queryForObject(
                "SELECT COUNT(*) FROM identity_account WHERE merchant_id=? AND role='MERCHANT_ADMIN' AND enabled=TRUE",
                Long.class,
                session.principal().merchantId());
    }

    private static void text(String value, int max, String label) {
        if (value == null || value.isBlank() || value.length() > max) throw invalid(label + "不能为空且不能超过" + max + "字");
    }

    private static CaseService.SemanticInvalidException invalid(String message) {
        return new CaseService.SemanticInvalidException(message);
    }

    private static void password(String value) {
        if (value == null || value.isBlank() || value.length() < 8 || value.length() > 200)
            throw invalid("密码需8–200位且不能全为空白");
    }

    private static String hash(String password) {
        byte[] salt = new byte[16];
        RANDOM.nextBytes(salt);
        return DemoAccounts.hashPassword(password, salt, 120000);
    }

    private static Role staffRole(String role) {
        if (!List.of("REVIEWER", "MERCHANT_ADMIN").contains(role == null ? "" : role))
            throw invalid("新增及工作人员角色仅支持售后专员或商家管理员");
        return Role.valueOf(role);
    }

    private static void match(Account target, String version) {
        if (version == null) throw new CaseStateConflictException("请携带打开维护时的账号版本");
        long expected;
        try {
            if (!version.matches("\"[1-9][0-9]{0,18}\"")) throw new NumberFormatException();
            expected = Long.parseLong(version.substring(1, version.length() - 1));
        } catch (NumberFormatException error) {
            throw invalid("If-Match需带引号的正整数账号版本");
        }
        if (expected != target.version()) throw new CaseStateConflictException("账号已被修改，请重新读取后核对");
    }

    private Map<String, Object> state(Account row) {
        return row == null
                ? null
                : Map.of("display_name", row.displayName(), "role", row.role().name(), "enabled", row.enabled());
    }

    private void audit(Session session, String action, String reason, Account before, Account after) {
        jdbc.update(
                "INSERT INTO identity_account_audit (merchant_id,target_username,actor_username,action,account_version,reason,before_state,after_state) VALUES (?,?,?,?,?,?,?,?)",
                session.principal().merchantId(),
                after.username(),
                session.principal().subject(),
                action,
                after.version(),
                reason,
                before == null ? null : json.writeValueAsString(state(before)),
                json.writeValueAsString(state(after)));
    }

    public Mutation create(Session session, Create request) {
        requireAdmin(session);
        if (request == null) throw invalid("请输入新增账号信息");
        if (request.username() == null || !request.username().matches("[A-Za-z0-9][A-Za-z0-9._-]{0,119}"))
            throw invalid("用户名需1–120位字母数字及._-，首位字母或数字");
        text(request.displayName(), 120, "显示姓名");
        text(request.reason(), 1000, "操作理由");
        password(request.password());
        Role role = staffRole(request.role());
        String hashed = hash(request.password());
        return writes.execute(status -> {
            lockCurrent(session, null);
            try {
                jdbc.update(
                        "INSERT INTO identity_account (username,merchant_id,role,display_name,password_hash) VALUES (?,?,?,?,?)",
                        request.username(),
                        session.principal().merchantId(),
                        role.name(),
                        request.displayName().trim(),
                        hashed);
            } catch (DuplicateKeyException error) {
                throw new CaseStateConflictException("用户名不可用，请选择其他用户名");
            }
            Account row = visible(session, request.username());
            audit(session, "CREATED", request.reason().trim(), null, row);
            return new Mutation(row, false);
        });
    }

    public Mutation update(Session session, String username, String version, Update request) {
        requireAdmin(session);
        if (request == null || request.enabled() == null || request.role() == null) throw invalid("请完整填写姓名、角色、启用状态和理由");
        text(request.displayName(), 120, "显示姓名");
        text(request.reason(), 1000, "操作理由");
        return writes.execute(status -> {
            Account before = lockCurrent(session, username);
            match(before, version);
            Role role;
            if (before.role() == Role.CUSTOMER || before.role() == Role.OPERATOR) {
                if (!before.role().name().equals(request.role())) throw invalid("客户及兼容运维账号的角色不可转换");
                role = before.role();
            } else role = staffRole(request.role());
            boolean securityChanged = role != before.role() || request.enabled() != before.enabled();
            if (before.enabled()
                    && before.role() == Role.MERCHANT_ADMIN
                    && (!request.enabled() || role != Role.MERCHANT_ADMIN)
                    && enabledAdmins(session) <= 1) throw new CaseStateConflictException("最后一个启用的管理员不能停用或降级");
            if (!securityChanged
                    && before.displayName().equals(request.displayName().trim())) return new Mutation(before, false);
            jdbc.update(
                    "UPDATE identity_account SET display_name=?,role=?,enabled=?,account_version=account_version+1,identity_version=identity_version+? WHERE merchant_id=? AND username=?",
                    request.displayName().trim(),
                    role.name(),
                    request.enabled(),
                    securityChanged ? 1 : 0,
                    session.principal().merchantId(),
                    before.username());
            Account after = visible(session, before.username());
            audit(session, "UPDATED", request.reason().trim(), before, after);
            return new Mutation(
                    after,
                    securityChanged
                            && before.username().equals(session.principal().subject()));
        });
    }

    public Mutation resetPassword(Session session, String username, String version, Password request) {
        requireAdmin(session);
        if (request == null) throw invalid("请输入密码和理由");
        password(request.password());
        text(request.reason(), 1000, "操作理由");
        String hashed = hash(request.password());
        return writes.execute(status -> {
            Account before = lockCurrent(session, username);
            match(before, version);
            jdbc.update(
                    "UPDATE identity_account SET password_hash=?,account_version=account_version+1,identity_version=identity_version+1 WHERE merchant_id=? AND username=?",
                    hashed,
                    session.principal().merchantId(),
                    before.username());
            Account after = visible(session, before.username());
            audit(session, "PASSWORD_RESET", request.reason().trim(), before, after);
            return new Mutation(
                    after, before.username().equals(session.principal().subject()));
        });
    }

    private static int limit(Integer value) {
        int applied = value == null ? 20 : value;
        if (applied < 1 || applied > 100) throw new InvalidPageException("limit需1–100");
        return applied;
    }

    private static String context(String value) {
        // A pagination fingerprint, not an authorization credential.
        return org.springframework.util.DigestUtils.md5DigestAsHex(value.getBytes(StandardCharsets.UTF_8));
    }

    private static String cursor(String context, String last) {
        return Base64.getUrlEncoder()
                .withoutPadding()
                .encodeToString((context + "\n" + last).getBytes(StandardCharsets.UTF_8));
    }

    private static String after(String cursor, String context) {
        if (cursor == null || cursor.isBlank()) return "";
        try {
            String[] parts = new String(Base64.getUrlDecoder().decode(cursor), StandardCharsets.UTF_8).split("\n", -1);
            if (parts.length != 2 || !parts[0].equals(context) || parts[1].isEmpty())
                throw new IllegalArgumentException();
            return parts[1];
        } catch (IllegalArgumentException error) {
            throw new InvalidPageException("游标与当前账号或筛选不符，请重新读取首页");
        }
    }

    @Transactional(readOnly = true, isolation = Isolation.REPEATABLE_READ)
    public Page list(Session session, String query, String role, String status, String cursor, Integer requestedLimit) {
        requireAdmin(session);
        String term = query == null ? "" : query.trim(),
                roleFilter = role == null ? "ALL" : role,
                statusFilter = status == null ? "ALL" : status;
        if (term.length() > 100
                || !List.of("ALL", "CUSTOMER", "REVIEWER", "MERCHANT_ADMIN", "OPERATOR")
                        .contains(roleFilter)
                || !List.of("ALL", "ENABLED", "DISABLED").contains(statusFilter))
            throw new InvalidPageException("账号筛选参数无效");
        int limit = limit(requestedLimit);
        String context = context(session.principal().merchantId() + "\n"
                + session.principal().subject() + "\n" + roleFilter + "\n" + statusFilter + "\n" + term);
        String last = after(cursor, context);
        String where =
                " WHERE merchant_id=? AND (?='ALL' OR role=?) AND (?='ALL' OR enabled=?) AND (?='' OR LOCATE(?,username)>0 OR LOCATE(?,display_name)>0)";
        Object[] params = {
            session.principal().merchantId(),
            roleFilter,
            roleFilter,
            statusFilter,
            statusFilter.equals("ENABLED"),
            term,
            term,
            term
        };
        long total = jdbc.queryForObject("SELECT COUNT(*) FROM identity_account" + where, Long.class, params);
        List<Object> pageParams = new ArrayList<>(List.of(params));
        pageParams.add(last);
        pageParams.add(limit + 1);
        var rows = jdbc.query(
                "SELECT username,display_name,role,enabled,account_version,created_at,updated_at FROM identity_account"
                        + where + " AND username>? ORDER BY username LIMIT ?",
                (rs, n) -> new Account(
                        rs.getString(1),
                        rs.getString(2),
                        Role.valueOf(rs.getString(3)),
                        rs.getBoolean(4),
                        rs.getLong(5),
                        rs.getTimestamp(6).toInstant(),
                        rs.getTimestamp(7).toInstant()),
                pageParams.toArray());
        boolean more = rows.size() > limit;
        var page = List.copyOf(more ? rows.subList(0, limit) : rows);
        return new Page(
                page,
                new PageMeta(limit, more ? cursor(context, page.getLast().username()) : null),
                total,
                enabledAdmins(session),
                session.principal().subject());
    }

    @Transactional(readOnly = true, isolation = Isolation.REPEATABLE_READ)
    public AuditPage history(Session session, String username, String cursor, Integer requestedLimit) {
        requireAdmin(session);
        Account target = visible(session, username);
        int limit = limit(requestedLimit);
        String context = context(
                session.principal().merchantId() + "\n" + session.principal().subject() + "\n" + target.username());
        String raw = after(cursor, context);
        long after;
        try {
            after = raw.isEmpty() ? Long.MAX_VALUE : Long.parseLong(raw);
            if (after < 1) throw new NumberFormatException();
        } catch (NumberFormatException error) {
            throw new InvalidPageException("审计游标无效");
        }
        String where = " WHERE merchant_id=? AND target_username=?";
        long total = jdbc.queryForObject(
                "SELECT COUNT(*) FROM identity_account_audit" + where,
                Long.class,
                session.principal().merchantId(),
                target.username());
        var rows = jdbc.query(
                "SELECT audit_id,action,actor_username,account_version,reason,occurred_at,before_state,after_state FROM identity_account_audit"
                        + where + " AND audit_id<? ORDER BY audit_id DESC LIMIT ?",
                (rs, n) -> new Audit(
                        rs.getString(1),
                        rs.getString(2),
                        rs.getString(3),
                        rs.getLong(4),
                        rs.getString(5),
                        rs.getTimestamp(6).toInstant(),
                        rs.getString(7) == null ? null : json.readValue(rs.getString(7), Map.class),
                        json.readValue(rs.getString(8), Map.class)),
                session.principal().merchantId(),
                target.username(),
                after,
                limit + 1);
        boolean more = rows.size() > limit;
        var page = List.copyOf(more ? rows.subList(0, limit) : rows);
        return new AuditPage(
                page, new PageMeta(limit, more ? cursor(context, page.getLast().id()) : null), total);
    }
}
