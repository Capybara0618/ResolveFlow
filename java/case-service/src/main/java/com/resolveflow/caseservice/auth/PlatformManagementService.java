package com.resolveflow.caseservice.auth;

import com.resolveflow.caseservice.order.RequestPrincipalResolver.Session;
import com.resolveflow.caseservice.shopping.CommerceShoppingClient;
import com.resolveflow.shared.security.DemoAccounts;
import com.resolveflow.shared.security.Role;
import com.resolveflow.shared.shopping.ManagementWire.StoreSync;
import java.security.SecureRandom;
import java.util.List;
import java.util.UUID;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Service;
import org.springframework.transaction.PlatformTransactionManager;
import org.springframework.transaction.support.TransactionTemplate;

/** Short local writes and a resumable catalog sync; no external call inside the identity transaction. */
@Service
public class PlatformManagementService {
    private final JdbcTemplate jdbc;
    private final TransactionTemplate writes;
    private final CommerceShoppingClient commerce;

    public PlatformManagementService(
            JdbcTemplate jdbc, PlatformTransactionManager manager, CommerceShoppingClient commerce) {
        this.jdbc = jdbc;
        this.writes = new TransactionTemplate(manager);
        this.commerce = commerce;
    }

    public record Merchant(
            String merchant_id,
            String name,
            String description,
            boolean enabled,
            boolean desired_enabled,
            long version,
            String sync_state,
            boolean policy_ready) {}

    public record Buyer(String username, String display_name, boolean enabled, long version) {}

    public record Merchants(List<Merchant> items) {}

    public record Buyers(List<Buyer> items) {}

    public record MerchantCreate(
            String merchant_id,
            String name,
            String description,
            String username,
            String display_name,
            String password,
            String reason) {
        @Override
        public String toString() {
            return "MerchantCreate[credentials redacted]";
        }
    }

    public record MerchantUpdate(
            String name, String description, Boolean enabled, Long expected_version, String reason) {}

    public record BuyerCreate(String username, String display_name, String password, String reason) {
        @Override
        public String toString() {
            return "BuyerCreate[credentials redacted]";
        }
    }

    public record BuyerUpdate(
            String display_name, Boolean enabled, String password, Long expected_version, String reason) {
        @Override
        public String toString() {
            return "BuyerUpdate[credentials redacted]";
        }
    }

    private static CommerceShoppingClient.Refused invalid(String message) {
        return new CommerceShoppingClient.Refused(400, "INVALID_ARGUMENT", message);
    }

    private static CommerceShoppingClient.Refused conflict() {
        return new CommerceShoppingClient.Refused(409, "VERSION_CONFLICT", "记录已存在或已变化，请刷新后核对");
    }

    private static void text(String value, int max) {
        if (value == null || value.isBlank() || value.length() > max) throw invalid("必填内容为空或超出长度限制");
    }

    private static void username(String value) {
        if (value == null || !value.matches("[a-zA-Z0-9][a-zA-Z0-9_-]{2,59}")) throw invalid("账号需3–60位字母、数字、下划线或短横线");
    }

    private static void password(String value) {
        if (value == null || value.isBlank() || value.length() < 6 || value.length() > 200) throw invalid("密码需6–200位");
    }

    private static String hash(String value) {
        byte[] salt = new byte[16];
        new SecureRandom().nextBytes(salt);
        return DemoAccounts.hashPassword(value, salt, 120000);
    }

    private void admin(Session s, boolean lock) {
        if (s.principal().role() != Role.PLATFORM_ADMIN)
            throw new CommerceShoppingClient.Refused(403, "FORBIDDEN_SCOPE", "仅平台管理员可维护商家和买家");
        var found = jdbc.queryForList(
                "SELECT username FROM identity_account WHERE username=? AND role='PLATFORM_ADMIN' AND enabled=TRUE AND identity_version=?"
                        + (lock ? " FOR UPDATE" : ""),
                String.class,
                s.principal().subject(),
                s.identityVersion());
        if (found.isEmpty())
            throw new com.resolveflow.caseservice.order.RequestPrincipalResolver.UnauthenticatedException(
                    "账号状态已变化，请重新登录");
    }

    private void audit(Session s, String target, String action, String reason) {
        jdbc.update(
                "INSERT INTO platform_management_audit(actor,target,action,reason) VALUES (?,?,?,?)",
                s.principal().subject(),
                target,
                action,
                reason.trim());
    }

    private Merchant merchant(String id) {
        var rows = jdbc.query(
                """
            SELECT m.*, EXISTS(SELECT 1 FROM policy_bundle p WHERE p.merchant_id=m.merchant_id
              AND p.effective_from<=UTC_TIMESTAMP(6) AND (p.effective_to IS NULL OR p.effective_to>UTC_TIMESTAMP(6))) AS policy_ready
            FROM identity_merchant m WHERE merchant_id=?
            """,
                (rs, n) -> new Merchant(
                        rs.getString("merchant_id"),
                        rs.getString("display_name"),
                        rs.getString("description"),
                        rs.getBoolean("enabled"),
                        rs.getBoolean("desired_enabled"),
                        rs.getLong("version"),
                        rs.getString("sync_state"),
                        rs.getBoolean("policy_ready")),
                id);
        if (rows.isEmpty()) throw new CommerceShoppingClient.Refused(404, "NOT_FOUND", "商家不存在");
        return rows.getFirst();
    }

    public Merchants merchants(Session s) {
        admin(s, false);
        return new Merchants(
                jdbc
                        .queryForList(
                                "SELECT merchant_id FROM identity_merchant ORDER BY merchant_id LIMIT 200",
                                String.class)
                        .stream()
                        .map(this::merchant)
                        .toList());
    }

    public Buyers buyers(Session s) {
        admin(s, false);
        return new Buyers(jdbc.query(
                "SELECT username,display_name,enabled,account_version FROM identity_account WHERE buyer_id IS NOT NULL ORDER BY username LIMIT 200",
                (rs, n) -> new Buyer(rs.getString(1), rs.getString(2), rs.getBoolean(3), rs.getLong(4))));
    }

    private Buyer buyer(String name) {
        return jdbc
                .query(
                        "SELECT username,display_name,enabled,account_version FROM identity_account WHERE username=? AND buyer_id IS NOT NULL",
                        (rs, n) -> new Buyer(rs.getString(1), rs.getString(2), rs.getBoolean(3), rs.getLong(4)),
                        name)
                .stream()
                .findFirst()
                .orElseThrow(() -> new CommerceShoppingClient.Refused(404, "NOT_FOUND", "买家不存在"));
    }

    private void bindAll(String buyer) {
        jdbc.update(
                "INSERT INTO buyer_customer_binding(buyer_id,merchant_id,customer_id) SELECT ?,merchant_id,CONCAT('C-',SUBSTRING(SHA2(CONCAT(?,':',merchant_id),256),1,40)) FROM identity_merchant",
                buyer,
                buyer);
    }

    public Buyer createBuyer(Session s, BuyerCreate r) {
        admin(s, false);
        if (r == null) throw invalid("请填写买家信息");
        username(r.username());
        text(r.display_name(), 120);
        text(r.reason(), 1000);
        password(r.password());
        String hashed = hash(r.password());
        return writes.execute(status -> {
            admin(s, true);
            if (!jdbc.queryForList("SELECT username FROM identity_account WHERE username=?", String.class, r.username())
                    .isEmpty()) throw conflict();
            String id = "B-" + UUID.randomUUID();
            jdbc.update("INSERT INTO platform_buyer(buyer_id) VALUES (?)", id);
            jdbc.update(
                    "INSERT INTO identity_account(username,role,buyer_id,display_name,password_hash) VALUES (?,'CUSTOMER',?,?,?)",
                    r.username(),
                    id,
                    r.display_name().trim(),
                    hashed);
            bindAll(id);
            audit(s, r.username(), "BUYER_CREATED", r.reason());
            return buyer(r.username());
        });
    }

    public Buyer updateBuyer(Session s, String name, BuyerUpdate r) {
        admin(s, false);
        if (r == null || r.enabled() == null || r.expected_version() == null) throw invalid("请输入买家状态及版本");
        text(r.display_name(), 120);
        text(r.reason(), 1000);
        if (r.password() != null) password(r.password());
        String hashed = r.password() == null ? null : hash(r.password());
        return writes.execute(status -> {
            admin(s, true);
            jdbc.queryForList("SELECT username FROM identity_account WHERE username=? FOR UPDATE", String.class, name);
            var before = buyer(name);
            if (before.version() != r.expected_version()) throw conflict();
            jdbc.update(
                    "UPDATE identity_account SET display_name=?,enabled=?,password_hash=COALESCE(?,password_hash),identity_version=identity_version+1,account_version=account_version+1 WHERE username=? AND buyer_id IS NOT NULL",
                    r.display_name().trim(),
                    r.enabled(),
                    hashed,
                    name);
            audit(s, name, "BUYER_UPDATED", r.reason());
            return buyer(name);
        });
    }

    public Merchant createMerchant(Session s, MerchantCreate r) {
        admin(s, false);
        if (r == null || r.merchant_id() == null || !r.merchant_id().matches("[A-Za-z0-9_-]{1,64}"))
            throw invalid("商家标识无效");
        username(r.username());
        text(r.name(), 120);
        text(r.description(), 500);
        text(r.display_name(), 120);
        text(r.reason(), 1000);
        password(r.password());
        String hashed = hash(r.password());
        writes.executeWithoutResult(status -> {
            admin(s, true);
            if (!jdbc.queryForList(
                            "SELECT merchant_id FROM identity_merchant WHERE merchant_id=? FOR UPDATE",
                            String.class,
                            r.merchant_id())
                    .isEmpty()) {
                var existing = merchant(r.merchant_id());
                var account = jdbc.queryForList(
                        "SELECT password_hash FROM identity_account WHERE username=? AND merchant_id=? AND role='MERCHANT_ADMIN'",
                        String.class,
                        r.username(),
                        r.merchant_id());
                if (!existing.name().equals(r.name().trim())
                        || !existing.description().equals(r.description().trim())
                        || account.isEmpty()
                        || !DemoAccounts.verify(r.password(), account.getFirst())) throw conflict();
                return;
            }
            if (!jdbc.queryForList("SELECT username FROM identity_account WHERE username=?", String.class, r.username())
                    .isEmpty()) throw conflict();
            jdbc.update(
                    "INSERT INTO identity_merchant(merchant_id,display_name,description,enabled,desired_enabled,sync_state,single_operator) VALUES (?,?,?,FALSE,TRUE,'PENDING',TRUE)",
                    r.merchant_id(),
                    r.name().trim(),
                    r.description().trim());
            jdbc.update(
                    "INSERT INTO identity_account(username,merchant_id,role,display_name,password_hash) VALUES (?,?,'MERCHANT_ADMIN',?,?)",
                    r.username(),
                    r.merchant_id(),
                    r.display_name().trim(),
                    hashed);
            jdbc.update(
                    "INSERT INTO buyer_customer_binding(buyer_id,merchant_id,customer_id) SELECT buyer_id,?,CONCAT('C-',SUBSTRING(SHA2(CONCAT(buyer_id,':',?),256),1,40)) FROM platform_buyer",
                    r.merchant_id(),
                    r.merchant_id());
            audit(s, r.merchant_id(), "MERCHANT_CREATED", r.reason());
        });
        return synchronize(s, r.merchant_id());
    }

    public Merchant updateMerchant(Session s, String id, MerchantUpdate r) {
        admin(s, false);
        if (r == null || r.enabled() == null || r.expected_version() == null) throw invalid("请输入商家状态及版本");
        text(r.name(), 120);
        text(r.description(), 500);
        text(r.reason(), 1000);
        writes.executeWithoutResult(status -> {
            admin(s, true);
            jdbc.queryForList(
                    "SELECT merchant_id FROM identity_merchant WHERE merchant_id=? FOR UPDATE", String.class, id);
            var before = merchant(id);
            if (before.version() != r.expected_version()) throw conflict();
            jdbc.update(
                    "UPDATE identity_merchant SET display_name=?,description=?,desired_enabled=?,enabled=FALSE,version=version+1,sync_state='PENDING' WHERE merchant_id=?",
                    r.name().trim(),
                    r.description().trim(),
                    r.enabled(),
                    id);
            jdbc.update(
                    "UPDATE identity_account SET identity_version=identity_version+1,account_version=account_version+1 WHERE merchant_id=?",
                    id);
            audit(s, id, "MERCHANT_UPDATED", r.reason());
        });
        return synchronize(s, id);
    }

    public Merchant synchronize(Session s, String id) {
        admin(s, false);
        var before = merchant(id);
        commerce.syncStore(
                new StoreSync(id, before.name(), before.description(), before.desired_enabled(), before.version()));
        writes.executeWithoutResult(status -> {
            admin(s, true);
            jdbc.update(
                    "UPDATE identity_merchant SET enabled=desired_enabled,sync_state='READY' WHERE merchant_id=? AND version=?",
                    id,
                    before.version());
        });
        return merchant(id);
    }
}
