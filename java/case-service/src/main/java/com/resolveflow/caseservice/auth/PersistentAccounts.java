package com.resolveflow.caseservice.auth;

import com.fasterxml.jackson.annotation.JsonInclude;
import com.fasterxml.jackson.annotation.JsonProperty;
import com.resolveflow.shared.security.AuthenticatedPrincipal;
import com.resolveflow.shared.security.DemoAccounts;
import com.resolveflow.shared.security.JwtCodec;
import com.resolveflow.shared.security.Role;
import java.time.Instant;
import java.util.Objects;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Service;

/** Case owns user identities. Every public request checks the persisted account, without a revocation cache. */
@Service
public class PersistentAccounts {
    private static final String DUMMY_HASH =
            "pbkdf2-sha256$120000$cmYtZGVtby1zYWx0LTEwMDE=$G5MeWCydEhAhLpYYPBP4JgezXRYer9cvRwsSBJu/SbU=";
    private final JdbcTemplate jdbc;
    private final JwtCodec codec;

    public PersistentAccounts(JdbcTemplate jdbc, JwtCodec codec) {
        this.jdbc = jdbc;
        this.codec = codec;
    }

    private record Account(
            String username,
            String merchantId,
            Role role,
            String customerId,
            String buyerId,
            String displayName,
            String merchantName,
            String passwordHash,
            boolean enabled,
            long identityVersion) {
        AuthenticatedPrincipal principal() {
            return new AuthenticatedPrincipal(username, merchantId, role, customerId, buyerId);
        }

        Profile profile() {
            return new Profile(username, merchantId, role, customerId, displayName, merchantName, buyerId);
        }
    }

    @JsonInclude(JsonInclude.Include.NON_NULL)
    public record Profile(
            String username,
            @JsonProperty("merchant_id") String merchantId,
            Role role,
            @JsonProperty("customer_id") String customerId,
            @JsonProperty("display_name") String displayName,
            @JsonProperty("merchant_name") String merchantName,
            @JsonProperty("buyer_id") String buyerId) {}

    private Account find(String username) {
        var rows = jdbc.query(
                """
                SELECT a.username,a.merchant_id,a.role,a.customer_id,a.buyer_id,a.display_name,a.password_hash,
                       a.identity_version,(a.enabled AND (a.role='PLATFORM_ADMIN' OR a.buyer_id IS NOT NULL OR m.enabled)) AS enabled,
                       m.display_name AS merchant_name
                  FROM identity_account a LEFT JOIN identity_merchant m ON m.merchant_id=a.merchant_id
                 WHERE a.username=?
                """,
                (rs, n) -> new Account(
                        rs.getString("username"),
                        rs.getString("merchant_id"),
                        Role.valueOf(rs.getString("role")),
                        rs.getString("customer_id"),
                        rs.getString("buyer_id"),
                        rs.getString("display_name"),
                        rs.getString("merchant_name"),
                        rs.getString("password_hash"),
                        rs.getBoolean("enabled"),
                        rs.getLong("identity_version")),
                username);
        return rows.isEmpty() ? null : rows.getFirst();
    }

    public LoginResponse login(String username, String password, Instant now) {
        Account account = find(username);
        boolean matches = DemoAccounts.verify(password, account == null ? DUMMY_HASH : account.passwordHash());
        if (!matches || account == null || !account.enabled()) throw new DemoAccounts.CredentialsRejectedException();
        String token = codec.issue(account.principal(), account.identityVersion(), now);
        return new LoginResponse(
                token,
                "Bearer",
                codec.timeToLive().getSeconds(),
                account.role(),
                account.merchantId(),
                account.customerId(),
                account.displayName(),
                account.merchantName(),
                account.buyerId());
    }

    public Profile requireCurrent(AuthenticatedPrincipal principal, long identityVersion) {
        Account account = find(principal.subject());
        if (account == null
                || !account.enabled()
                || account.identityVersion() != identityVersion
                || !Objects.equals(account.merchantId(), principal.merchantId())
                || account.role() != principal.role()
                || !Objects.equals(account.buyerId(), principal.buyerId())
                || !Objects.equals(account.customerId(), principal.customerId()))
            throw new JwtCodec.TokenException("user session is no longer current");
        return account.profile();
    }
}
