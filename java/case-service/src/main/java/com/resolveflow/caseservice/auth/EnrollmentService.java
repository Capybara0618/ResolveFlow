package com.resolveflow.caseservice.auth;

import com.resolveflow.caseservice.order.RequestPrincipalResolver.Session;
import com.resolveflow.caseservice.shopping.CommerceShoppingClient.Refused;
import com.resolveflow.shared.security.DemoAccounts;
import java.nio.charset.StandardCharsets;
import java.security.*;
import java.time.Clock;
import java.util.*;
import org.springframework.dao.DuplicateKeyException;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Service;
import org.springframework.transaction.PlatformTransactionManager;
import org.springframework.transaction.support.TransactionTemplate;

@Service
public class EnrollmentService {
    public record Register(String username, String display_name, String password) {
        @Override
        public String toString() {
            return "Register[redacted]";
        }
    }

    public record Recover(String username, String recovery_key, String new_password) {
        @Override
        public String toString() {
            return "Recover[redacted]";
        }
    }

    public record Rotate(String current_password) {
        @Override
        public String toString() {
            return "Rotate[redacted]";
        }
    }

    public record ChangeLogin(String login_name, String current_password, Long expected_version) {
        @Override
        public String toString() {
            return "ChangeLogin[redacted]";
        }
    }

    public record LoginChanged(String login_name) {}

    public record Receipt(String username, String recovery_key) {
        @Override
        public String toString() {
            return "Receipt[redacted]";
        }
    }

    private record Window(long at, int count) {}

    private final Map<String, Window> attempts = new HashMap<>();
    private final JdbcTemplate db;
    private final TransactionTemplate tx;
    private final Clock clock;

    public EnrollmentService(JdbcTemplate db, PlatformTransactionManager manager, Clock clock) {
        this.db = db;
        tx = new TransactionTemplate(manager);
        this.clock = clock;
    }

    private synchronized void limit(String key, int maximum) {
        long now = clock.millis();
        attempts.entrySet().removeIf(e -> now - e.getValue().at() > 600000);
        var w = attempts.getOrDefault(key, new Window(now, 0));
        if (attempts.size() >= 4096 && !attempts.containsKey(key) || w.count() >= maximum)
            throw new Refused(429, "TOO_MANY_ATTEMPTS", "操作过于频繁，请稍后再试");
        attempts.put(key, new Window(w.at(), w.count() + 1));
    }

    private static void username(String value) {
        if (value == null || !value.matches("[a-zA-Z0-9][a-zA-Z0-9_-]{2,59}")) throw invalid("账号需3–60位字母、数字、下划线或短横线");
    }

    private static void password(String value) {
        if (value == null || value.isBlank() || value.length() < 8 || value.length() > 200) throw invalid("密码需8–200位");
    }

    private static Refused invalid(String message) {
        return new Refused(400, "INVALID_ARGUMENT", message);
    }

    private static String random(int length) {
        byte[] bytes = new byte[length];
        new SecureRandom().nextBytes(bytes);
        return HexFormat.of().formatHex(bytes);
    }

    private static String hashPassword(String value) {
        return DemoAccounts.hashPassword(value, HexFormat.of().parseHex(random(16)), 120000);
    }

    private static String digest(String value) {
        try {
            return HexFormat.of()
                    .formatHex(MessageDigest.getInstance("SHA-256").digest(value.getBytes(StandardCharsets.UTF_8)));
        } catch (NoSuchAlgorithmException e) {
            throw new IllegalStateException(e);
        }
    }

    private Receipt key(String user) {
        String key = random(32);
        db.update(
                "INSERT INTO account_recovery(username,token_hash) VALUES(?,?) ON DUPLICATE KEY UPDATE token_hash=VALUES(token_hash),issued_at=CURRENT_TIMESTAMP(6)",
                user,
                digest(key));
        return new Receipt(user, key);
    }

    public Receipt register(Register r, String peer) {
        limit("register:" + peer, 10);
        username(r.username());
        password(r.password());
        if (r.display_name() == null
                || r.display_name().isBlank()
                || r.display_name().trim().length() > 120
                || r.display_name().chars().anyMatch(Character::isISOControl)) throw invalid("请填写有效昵称");
        String hash = hashPassword(r.password());
        try {
            return tx.execute(st -> {
                String buyer = "B-" + UUID.randomUUID();
                db.update("INSERT INTO platform_buyer(buyer_id) VALUES (?)", buyer);
                db.update(
                        "INSERT INTO identity_account(username,role,buyer_id,display_name,password_hash) VALUES (?,'CUSTOMER',?,?,?)",
                        r.username(),
                        buyer,
                        r.display_name().trim(),
                        hash);
                db.update(
                        "INSERT INTO buyer_customer_binding(buyer_id,merchant_id,customer_id) SELECT ?,merchant_id,CONCAT('C-',SUBSTRING(SHA2(CONCAT(?,':',merchant_id),256),1,40)) FROM identity_merchant",
                        buyer,
                        buyer);
                return key(r.username());
            });
        } catch (DuplicateKeyException e) {
            throw new Refused(409, "USERNAME_UNAVAILABLE", "该账号暂不可用，请换一个账号名");
        }
    }

    public Receipt recover(Recover r, String peer) {
        limit("recover-peer:" + peer, 20);
        username(r.username());
        limit("recover-user:" + r.username(), 5);
        password(r.new_password());
        String supplied = r.recovery_key() == null ? "" : r.recovery_key().trim();
        if (!supplied.matches("[a-f0-9]{64}")) throw invalid("账号或恢复密钥不匹配");
        String next = hashPassword(r.new_password());
        return tx.execute(st -> {
            var accounts = db.queryForList(
                    "SELECT username FROM identity_account WHERE login_key=? AND buyer_id IS NOT NULL AND enabled=TRUE FOR UPDATE",
                    String.class,
                    r.username());
            String subject = accounts.isEmpty() ? r.username() : accounts.getFirst();
            var saved = db.queryForList(
                    "SELECT token_hash FROM account_recovery WHERE username=? FOR UPDATE", String.class, subject);
            String stored = saved.isEmpty() ? "0".repeat(64) : saved.getFirst();
            boolean match = MessageDigest.isEqual(
                    stored.getBytes(StandardCharsets.US_ASCII), digest(supplied).getBytes(StandardCharsets.US_ASCII));
            if (accounts.isEmpty() || saved.isEmpty() || !match) throw invalid("账号或恢复密钥不匹配");
            db.update(
                    "UPDATE identity_account SET password_hash=?,identity_version=identity_version+1,account_version=account_version+1 WHERE username=?",
                    next,
                    subject);
            var receipt = key(subject);
            return new Receipt(r.username(), receipt.recovery_key());
        });
    }

    public LoginChanged changeLogin(Session s, ChangeLogin r) {
        if (!s.principal().isPlatformBuyer()) throw new Refused(403, "FORBIDDEN_SCOPE", "请使用买家账号");
        limit("login-name:" + s.principal().subject(), 5);
        username(r.login_name());
        if (r.current_password() == null || r.current_password().length() > 200) throw invalid("请输入当前密码");
        try {
            return tx.execute(st -> {
                var rows = db.queryForList(
                        "SELECT password_hash,profile_version,login_key FROM identity_account WHERE username=? AND enabled=TRUE AND identity_version=? FOR UPDATE",
                        s.principal().subject(),
                        s.identityVersion());
                if (rows.isEmpty()) throw new Refused(401, "UNAUTHENTICATED", "登录已失效，请重新登录");
                var row = rows.getFirst();
                if (r.expected_version() == null
                        || ((Number) row.get("profile_version")).longValue() != r.expected_version())
                    throw new Refused(409, "VERSION_CONFLICT", "资料已更新，请刷新后重试");
                if (!DemoAccounts.verify(
                        r.current_password(), row.get("password_hash").toString())) throw invalid("当前密码不正确");
                // Lock the canonical-name index gap too: aliases cannot impersonate another immutable subject.
                var reserved = db.queryForList(
                        "SELECT username FROM identity_account WHERE username=? FOR UPDATE",
                        String.class,
                        r.login_name());
                if (!reserved.isEmpty()
                        && !reserved.getFirst().equals(s.principal().subject()))
                    throw new Refused(409, "USERNAME_UNAVAILABLE", "该账号已被使用");
                if (r.login_name().equals(row.get("login_key"))) return new LoginChanged(r.login_name());
                db.update(
                        "UPDATE identity_account SET login_name=?,profile_version=profile_version+1,identity_version=identity_version+1,account_version=account_version+1 WHERE username=?",
                        r.login_name(),
                        s.principal().subject());
                return new LoginChanged(r.login_name());
            });
        } catch (DuplicateKeyException e) {
            throw new Refused(409, "USERNAME_UNAVAILABLE", "该账号已被使用");
        }
    }

    public Receipt rotate(Session s, Rotate r) {
        if (!s.principal().isPlatformBuyer()) throw new Refused(403, "FORBIDDEN_SCOPE", "请使用买家账号");
        limit("rotate:" + s.principal().subject(), 5);
        if (r.current_password() == null || r.current_password().length() > 200) throw invalid("请输入当前密码");
        return tx.execute(st -> {
            var hashes = db.queryForList(
                    "SELECT password_hash FROM identity_account WHERE username=? AND enabled=TRUE AND identity_version=? FOR UPDATE",
                    String.class,
                    s.principal().subject(),
                    s.identityVersion());
            if (hashes.isEmpty()) throw new Refused(401, "UNAUTHENTICATED", "登录已失效，请重新登录");
            if (!DemoAccounts.verify(r.current_password(), hashes.getFirst())) throw invalid("当前密码不正确");
            return key(s.principal().subject());
        });
    }
}
