package com.resolveflow.shared.security;

import java.security.GeneralSecurityException;
import java.security.MessageDigest;
import java.time.Instant;
import java.util.Base64;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import javax.crypto.SecretKeyFactory;
import javax.crypto.spec.PBEKeySpec;

/**
 * The seeded demonstration accounts: two synthetic merchants, each with a customer and a reviewer,
 * plus a local-only operator.
 *
 * <p>Authorities: docs/product-spec.md:9 keeps CUSTOMER/REVIEWER/OPERATOR, asks for two synthetic
 * merchants with at least two users each (so isolation is testable at all), and rules out tenant
 * billing or onboarding; docs/domain-model.md:24 says the account stores a password <em>hash</em>.
 * The passwords below are the demonstration ones the core OpenAPI example shows, and the hashes are
 * PBKDF2-SHA256 over per-account salts — not a deployment credential store, but not plaintext either.
 *
 * <p>This table is the seed C01.2 moves into the {@code demo_user} migration; keeping it here first
 * means the login path is testable before any database exists.
 */
public final class DemoAccounts {

    private static final String HASH_PREFIX = "pbkdf2-sha256";
    private static final int ITERATIONS = 120_000;
    private static final int KEY_LENGTH_BITS = 256;

    /** A seed account. The hash is what gets stored; the password is never held here. */
    public record Account(String username, String merchantId, Role role, String customerId, String passwordHash) {

        public Account {
            if (username == null || username.isBlank()) {
                throw new IllegalArgumentException("an account needs a username");
            }
            if (merchantId == null || merchantId.isBlank()) {
                throw new IllegalArgumentException("an account needs a merchant_id");
            }
            if (role == null) {
                throw new IllegalArgumentException("an account needs a role");
            }
            if (role.isCustomerScoped() == (customerId == null)) {
                throw new IllegalArgumentException("customer_id is present exactly for a CUSTOMER account");
            }
        }
    }

    /** What a successful login returns; the field names match the core OpenAPI LoginResponse. */
    public record Login(
            String accessToken, String tokenType, long expiresIn, Role role, String merchantId, String customerId) {}

    /** Raised for both a wrong password and an unknown account, with one identical message. */
    public static class CredentialsRejectedException extends RuntimeException {

        private static final long serialVersionUID = 1L;

        public CredentialsRejectedException() {
            super("invalid username or password");
        }
    }

    private static final List<Account> SEED = List.of(
            new Account(
                    "demo-customer",
                    "M-1001",
                    Role.CUSTOMER,
                    "C-2002",
                    "pbkdf2-sha256$120000$cmYtZGVtby1zYWx0LTEwMDE=$G5MeWCydEhAhLpYYPBP4JgezXRYer9cvRwsSBJu/SbU="),
            new Account(
                    "demo-customer-2",
                    "M-1001",
                    Role.CUSTOMER,
                    "C-2003",
                    "pbkdf2-sha256$120000$cmYtZGVtby1zYWx0LTEwMDI=$8ZZCK8echvJI6B6vt4SXlZ9c/2FzjNv7g8xyLO3QXIg="),
            new Account(
                    "demo-reviewer",
                    "M-1001",
                    Role.REVIEWER,
                    null,
                    "pbkdf2-sha256$120000$cmYtZGVtby1zYWx0LTEwMDM=$/deceRbcZEJxA8CoJk1+KnCKigNA8zapz4qYN7AVjb0="),
            new Account(
                    "demo-customer-m2",
                    "M-1002",
                    Role.CUSTOMER,
                    "C-2004",
                    "pbkdf2-sha256$120000$cmYtZGVtby1zYWx0LTIwMDE=$WhNrU7h45lXeVMNJoDYbj2bhfJiqzuHg2wO3BI/UbJ4="),
            new Account(
                    "demo-reviewer-m2",
                    "M-1002",
                    Role.REVIEWER,
                    null,
                    "pbkdf2-sha256$120000$cmYtZGVtby1zYWx0LTIwMDI=$pF6OwNSBSyYHxbbLnHcrCrgKjA8PQYSMg79rF/m8DqA="),
            new Account(
                    "demo-operator",
                    "M-1001",
                    Role.OPERATOR,
                    null,
                    "pbkdf2-sha256$120000$cmYtZGVtby1zYWx0LTMwMDE=$k5q+LSlQER9YsONkgU7ev/Xn2+lpOOzvEJWW9zsITX4="));

    /** A hash the unknown-account path verifies against, so timing does not reveal the username. */
    private static final String DUMMY_HASH = HASH_PREFIX
            + "$"
            + ITERATIONS
            + "$"
            + Base64.getEncoder().encodeToString(new byte[16])
            + "$"
            + Base64.getEncoder().encodeToString(new byte[KEY_LENGTH_BITS / 8]);

    private final JwtCodec codec;
    private final Map<String, Account> byUsername;

    public DemoAccounts(JwtCodec codec) {
        this.codec = codec;
        Map<String, Account> table = new LinkedHashMap<>();
        for (Account account : SEED) {
            table.put(account.username(), account);
        }
        this.byUsername = Map.copyOf(table);
    }

    public List<Account> all() {
        return SEED;
    }

    /**
     * Exchange an account for a user token.
     *
     * <p>The merchant comes from the account: the method has no merchant parameter, so a caller cannot
     * ask to be someone else (docs/core-contracts.md:15). Unknown accounts still perform the key
     * derivation, so the failure does not announce whether the username exists.
     */
    public Login login(String username, String password, Instant now) {
        Account account = username == null ? null : byUsername.get(username);
        boolean passwordMatches = verify(password, account == null ? DUMMY_HASH : account.passwordHash());
        if (account == null || !passwordMatches) {
            throw new CredentialsRejectedException();
        }
        AuthenticatedPrincipal principal = new AuthenticatedPrincipal(
                account.username(), account.merchantId(), account.role(), account.customerId());
        String token = codec.issue(principal, now);
        return new Login(
                token,
                "Bearer",
                codec.timeToLive().getSeconds(),
                account.role(),
                account.merchantId(),
                account.customerId());
    }

    /** Verify a stored {@code pbkdf2-sha256$iterations$salt$hash} value in constant time. */
    static boolean verify(String password, String stored) {
        if (password == null || stored == null) {
            return false;
        }
        String[] parts = stored.split("\\$");
        if (parts.length != 4 || !HASH_PREFIX.equals(parts[0])) {
            return false;
        }
        int iterations;
        byte[] salt;
        byte[] expected;
        try {
            iterations = Integer.parseInt(parts[1]);
            salt = Base64.getDecoder().decode(parts[2]);
            expected = Base64.getDecoder().decode(parts[3]);
        } catch (IllegalArgumentException error) {
            return false;
        }
        byte[] derived = derive(password, salt, iterations, expected.length * 8);
        return derived != null && MessageDigest.isEqual(derived, expected);
    }

    private static byte[] derive(String password, byte[] salt, int iterations, int keyLengthBits) {
        try {
            PBEKeySpec spec = new PBEKeySpec(password.toCharArray(), salt, iterations, keyLengthBits);
            try {
                return SecretKeyFactory.getInstance("PBKDF2WithHmacSHA256")
                        .generateSecret(spec)
                        .getEncoded();
            } finally {
                spec.clearPassword();
            }
        } catch (GeneralSecurityException error) {
            throw new IllegalStateException("PBKDF2WithHmacSHA256 is required by JDK 21", error);
        }
    }

    /** The hash format, exposed so a seeding tool does not have to duplicate it. */
    public static String hashPassword(String password, byte[] salt, int iterations) {
        byte[] derived = derive(password, salt, iterations, KEY_LENGTH_BITS);
        if (derived == null) {
            throw new IllegalStateException("derivation failed");
        }
        Base64.Encoder encoder = Base64.getEncoder();
        return HASH_PREFIX + "$" + iterations + "$" + encoder.encodeToString(salt) + "$"
                + encoder.encodeToString(derived);
    }
}
