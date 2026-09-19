package com.resolveflow.shared.security;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

import java.time.Instant;
import java.util.List;
import java.util.Map;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

/**
 * The seeded demonstration accounts.
 *
 * <p>Authority: docs/product-spec.md:9 keeps CUSTOMER, REVIEWER and a local-only OPERATOR, and asks
 * for two synthetic merchants with at least two users each so isolation is testable;
 * docs/domain-model.md:24 says the account stores a password hash rather than a password. The
 * accounts are demonstration material: the passwords are the ones the core OpenAPI examples use, and
 * the secrets below are not deployment keys.
 */
class DemoAccountsTest {

    private static final Instant NOW = Instant.parse("2026-09-19T10:00:00Z");

    private static DemoAccounts accounts() {
        return new DemoAccounts(
                new JwtCodec("demo-identity-secret-not-a-deployment-key", java.time.Duration.ofHours(1)));
    }

    @Test
    @DisplayName("two merchants exist, each with a customer and a reviewer")
    void twoMerchantsWithTwoUsersEach() {
        List<DemoAccounts.Account> all = accounts().all();

        assertThat(all.stream().map(DemoAccounts.Account::merchantId).distinct())
                .hasSize(2);
        for (String merchant : List.of("M-1001", "M-1002")) {
            List<DemoAccounts.Account> users = all.stream()
                    .filter(account -> account.merchantId().equals(merchant))
                    .toList();
            assertThat(users.stream().map(DemoAccounts.Account::role))
                    .as("merchant %s needs a customer and a reviewer (docs/product-spec.md:9)", merchant)
                    .contains(Role.CUSTOMER, Role.REVIEWER);
        }
    }

    @Test
    @DisplayName("the account the core OpenAPI example uses exists with the same values")
    void theDocumentedExampleAccountExists() {
        DemoAccounts.Login login = accounts().login("demo-customer", "demo-pass-1001", NOW);

        assertThat(login.role()).isEqualTo(Role.CUSTOMER);
        assertThat(login.merchantId()).isEqualTo("M-1001");
        assertThat(login.customerId()).isEqualTo("C-2002");
        assertThat(login.tokenType()).isEqualTo("Bearer");
        assertThat(login.expiresIn()).isPositive();
        assertThat(login.accessToken()).isNotBlank();
    }

    @Test
    @DisplayName("a wrong password and an unknown account fail identically")
    void failuresDoNotRevealWhichHalfWasWrong() {
        DemoAccounts accounts = accounts();

        assertThatThrownBy(() -> accounts.login("demo-customer", "wrong", NOW))
                .isInstanceOf(DemoAccounts.CredentialsRejectedException.class)
                .hasMessage("invalid username or password");
        assertThatThrownBy(() -> accounts.login("no-such-user", "demo-pass-1001", NOW))
                .isInstanceOf(DemoAccounts.CredentialsRejectedException.class)
                .hasMessage("invalid username or password");
    }

    @Test
    @DisplayName("the account table stores hashes, never the passwords themselves")
    void passwordsAreNotStoredInClear() {
        DemoAccounts accounts = accounts();

        for (DemoAccounts.Account account : accounts.all()) {
            assertThat(account.passwordHash())
                    .as("docs/domain-model.md:24 stores a password hash")
                    .startsWith("pbkdf2-sha256$")
                    .doesNotContain("demo-pass");
        }
    }

    @Test
    @DisplayName("every seeded account can sign in and yields its own principal")
    void everyAccountSignsIn() {
        DemoAccounts accounts = accounts();
        JwtCodec codec = new JwtCodec("demo-identity-secret-not-a-deployment-key", java.time.Duration.ofHours(1));

        // The passwords live here rather than in the account table, which stores hashes
        // (docs/domain-model.md:24). These are the demonstration credentials.
        Map<String, String> demoPasswords = Map.of(
                "demo-customer", "demo-pass-1001",
                "demo-customer-2", "demo-pass-1002",
                "demo-reviewer", "demo-pass-1003",
                "demo-customer-m2", "demo-pass-2001",
                "demo-reviewer-m2", "demo-pass-2002",
                "demo-operator", "demo-pass-3001");

        assertThat(demoPasswords.keySet())
                .as("every seeded account needs a known demonstration password in this test")
                .containsExactlyInAnyOrderElementsOf(accounts.all().stream()
                        .map(DemoAccounts.Account::username)
                        .toList());
        for (DemoAccounts.Account account : accounts.all()) {
            DemoAccounts.Login login = accounts.login(account.username(), demoPasswords.get(account.username()), NOW);
            AuthenticatedPrincipal principal = codec.verifyAsUser(login.accessToken(), NOW);
            assertThat(principal.merchantId()).isEqualTo(account.merchantId());
            assertThat(principal.role()).isEqualTo(account.role());
        }
    }

    @Test
    @DisplayName("the issued token's merchant comes from the account, not from the caller")
    void merchantComesFromTheAccount() {
        DemoAccounts accounts = accounts();

        // The login signature has no merchant parameter at all: the only way to ask for another
        // merchant is to authenticate as one of its users (docs/core-contracts.md:15).
        DemoAccounts.Login second = accounts.login("demo-customer-2", "demo-pass-1002", NOW);
        DemoAccounts.Login other = accounts.login("demo-customer-m2", "demo-pass-2001", NOW);

        assertThat(second.merchantId()).isEqualTo("M-1001");
        assertThat(other.merchantId()).isEqualTo("M-1002");
        assertThat(other.customerId()).isNotEqualTo(second.customerId());
    }

    @Test
    @DisplayName("an operator exists and is marked as local operations only")
    void operatorIsLocalOnly() {
        List<DemoAccounts.Account> operators = accounts().all().stream()
                .filter(account -> account.role() == Role.OPERATOR)
                .toList();

        assertThat(operators).isNotEmpty();
        assertThat(operators)
                .allSatisfy(account -> assertThat(account.customerId()).isNull());
    }
}
