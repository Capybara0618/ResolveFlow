package com.resolveflow.caseservice.auth;

import static org.assertj.core.api.Assertions.*;

import com.resolveflow.caseservice.CaseDatabaseTest;
import com.resolveflow.caseservice.order.RequestPrincipalResolver.Session;
import com.resolveflow.caseservice.shopping.CommerceShoppingClient.Refused;
import com.resolveflow.shared.security.Role;
import java.util.UUID;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;

class EnrollmentServiceTest extends CaseDatabaseTest {
    @Autowired
    EnrollmentService service;

    @Autowired
    PersistentAccounts accounts;

    String name() {
        return "signup-" + UUID.randomUUID().toString().substring(0, 12);
    }

    @Test
    void loginNameChangesKeepTheBuyerSubjectRejectCollisionsAndInvalidateOldSessions() {
        String user = name(),
                alias = name(),
                other = name(),
                peer = UUID.randomUUID().toString();
        var receipt = service.register(new EnrollmentService.Register(user, "测试改账号", "password-test"), peer);
        service.register(new EnrollmentService.Register(other, "其他买家", "password-test"), peer);
        String buyer = dbBuyer(user);
        var principal = new com.resolveflow.shared.security.AuthenticatedPrincipal(user, null, Role.CUSTOMER, buyer);
        long identityVersion =
                jdbc.queryForObject("SELECT identity_version FROM identity_account WHERE username=?", Long.class, user);
        var session = new Session(principal, identityVersion);
        assertThatThrownBy(() ->
                        service.changeLogin(session, new EnrollmentService.ChangeLogin(alias, "wrong-password", 1L)))
                .isInstanceOf(Refused.class)
                .hasMessage("当前密码不正确");
        assertThatThrownBy(() ->
                        service.changeLogin(session, new EnrollmentService.ChangeLogin(other, "password-test", 1L)))
                .isInstanceOf(Refused.class)
                .hasMessage("该账号已被使用");
        service.changeLogin(session, new EnrollmentService.ChangeLogin(alias, "password-test", 1L));
        assertThat(dbBuyer(user)).isEqualTo(buyer);
        assertThat(accounts.login(alias, "password-test", java.time.Instant.now())
                        .buyerId())
                .isEqualTo(buyer);
        assertThatThrownBy(() -> accounts.login(user, "password-test", java.time.Instant.now()))
                .isInstanceOf(com.resolveflow.shared.security.DemoAccounts.CredentialsRejectedException.class);
        assertThatThrownBy(() -> accounts.requireCurrent(principal, identityVersion))
                .isInstanceOf(com.resolveflow.shared.security.JwtCodec.TokenException.class);
        assertThatThrownBy(() -> service.register(new EnrollmentService.Register(alias, "冲突", "password-test"), peer))
                .isInstanceOf(Refused.class);
        var rotated = service.rotate(
                new Session(principal, identityVersion + 1), new EnrollmentService.Rotate("password-test"));
        assertThat(rotated.username()).isEqualTo(alias);
        assertThat(rotated.recovery_key()).isNotEqualTo(receipt.recovery_key());
        var recovered =
                service.recover(new EnrollmentService.Recover(alias, rotated.recovery_key(), "new-password"), peer);
        assertThat(recovered.username()).isEqualTo(alias);
        assertThat(accounts.login(alias, "new-password", java.time.Instant.now())
                        .buyerId())
                .isEqualTo(buyer);
        assertThatThrownBy(() ->
                        service.changeLogin(session, new EnrollmentService.ChangeLogin(name(), "new-password", 2L)))
                .isInstanceOf(Refused.class);
    }

    @Test
    void buyerRegistrationCreatesGlobalIdentityAndRecoveryInvalidatesOldLogin() {
        String user = name(), peer = UUID.randomUUID().toString();
        var result = service.register(new EnrollmentService.Register(user, "测试新买家", "password-test"), peer);
        var login = accounts.login(user, "password-test", java.time.Instant.now());
        assertThat(login.role()).isEqualTo(Role.CUSTOMER);
        assertThat(result.recovery_key()).hasSize(64);
        var buyer = dbBuyer(user);
        assertThat(jdbc.queryForObject(
                        "SELECT COUNT(*) FROM identity_account WHERE buyer_id=? AND merchant_id IS NULL",
                        Integer.class,
                        buyer))
                .isGreaterThan(0);
        var stored =
                jdbc.queryForObject("SELECT token_hash FROM account_recovery WHERE username=?", String.class, user);
        assertThat(stored).doesNotContain(result.recovery_key());
        long version =
                jdbc.queryForObject("SELECT identity_version FROM identity_account WHERE username=?", Long.class, user);
        var next = service.recover(new EnrollmentService.Recover(user, result.recovery_key(), "new-password"), peer);
        assertThat(next.recovery_key()).isNotEqualTo(result.recovery_key());
        assertThatThrownBy(() -> accounts.login(user, "password-test", java.time.Instant.now()))
                .isInstanceOf(com.resolveflow.shared.security.DemoAccounts.CredentialsRejectedException.class);
        assertThatThrownBy(() -> service.recover(
                        new EnrollmentService.Recover(user, result.recovery_key(), "another-pass"), peer))
                .isInstanceOf(Refused.class);
        assertThat(jdbc.queryForObject(
                        "SELECT identity_version FROM identity_account WHERE username=?", Long.class, user))
                .isEqualTo(version + 1);
        assertThat(accounts.login(user, "new-password", java.time.Instant.now()).role())
                .isEqualTo(Role.CUSTOMER);
    }

    String dbBuyer(String user) {
        return jdbc.queryForObject("SELECT buyer_id FROM identity_account WHERE username=?", String.class, user);
    }

    @Test
    void duplicateRegistrationRollsBackAndWrongKeyCannotResetPassword() {
        String user = name(), peer = UUID.randomUUID().toString();
        service.register(new EnrollmentService.Register(user, "测试买家", "password-test"), peer);
        long before = jdbc.queryForObject("SELECT COUNT(*) FROM platform_buyer", Long.class);
        assertThatThrownBy(() -> service.register(new EnrollmentService.Register(user, "重复", "password-test"), peer))
                .isInstanceOf(Refused.class);
        assertThat(jdbc.queryForObject("SELECT COUNT(*) FROM platform_buyer", Long.class))
                .isEqualTo(before);
        assertThatThrownBy(() ->
                        service.recover(new EnrollmentService.Recover(user, "0".repeat(64), "new-password"), peer))
                .isInstanceOf(Refused.class);
        assertThat(accounts.login(user, "password-test", java.time.Instant.now())
                        .role())
                .isEqualTo(Role.CUSTOMER);
    }

    @Test
    void recoveryKeyRotationRequiresCurrentPasswordAndRevokedSessionsCannotRotate() {
        String user = name(), peer = UUID.randomUUID().toString();
        var receipt = service.register(new EnrollmentService.Register(user, "测试买家", "password-test"), peer);
        var principal =
                new com.resolveflow.shared.security.AuthenticatedPrincipal(user, null, Role.CUSTOMER, dbBuyer(user));
        long version =
                jdbc.queryForObject("SELECT identity_version FROM identity_account WHERE username=?", Long.class, user);
        var session = new Session(principal, version);
        assertThatThrownBy(() -> service.rotate(session, new EnrollmentService.Rotate("wrong")))
                .isInstanceOf(Refused.class);
        var updated = service.rotate(session, new EnrollmentService.Rotate("password-test"));
        assertThat(updated.recovery_key()).isNotEqualTo(receipt.recovery_key());
        service.recover(new EnrollmentService.Recover(user, updated.recovery_key(), "new-password"), peer);
        assertThatThrownBy(() -> service.rotate(session, new EnrollmentService.Rotate("new-password")))
                .isInstanceOf(Refused.class);
        assertThatThrownBy(() -> accounts.requireCurrent(principal, version))
                .isInstanceOf(com.resolveflow.shared.security.JwtCodec.TokenException.class);
    }
}
