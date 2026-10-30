package com.resolveflow.caseservice.auth;

import static org.assertj.core.api.Assertions.*;

import com.resolveflow.caseservice.CaseDatabaseTest;
import com.resolveflow.caseservice.order.RequestPrincipalResolver.Session;
import com.resolveflow.caseservice.shopping.CommerceShoppingClient.Refused;
import com.resolveflow.shared.security.AuthenticatedPrincipal;
import com.resolveflow.shared.security.Role;
import java.util.List;
import java.util.concurrent.Executors;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;

class AccountServiceTest extends CaseDatabaseTest {
    @Autowired
    AccountService service;

    private Session session(String user) {
        return new Session(new AuthenticatedPrincipal(user, null, Role.CUSTOMER, null, user), 1);
    }

    private AccountService.EditAddress address(boolean primary, Long version) {
        return new AccountService.EditAddress("演示收货人", "13800000000", "浙江省", "杭州市", "西湖区", "演示路1号", primary, version);
    }

    @BeforeEach
    void prepare() {
        for (String name : List.of("profile-test-one", "profile-test-two")) {
            jdbc.update("DELETE FROM buyer_address WHERE buyer_id=?", name);
            jdbc.update("DELETE FROM identity_account WHERE username=?", name);
            jdbc.update("INSERT IGNORE INTO platform_buyer(buyer_id) VALUES (?)", name);
            jdbc.update(
                    "INSERT INTO identity_account(username,role,buyer_id,display_name,password_hash,identity_version) VALUES (?,'CUSTOMER',?,'测试买家','unused',1)",
                    name,
                    name);
        }
    }

    @Test
    void optionalProfileFieldsPersistAndRejectInvalidValuesWithVersionProtection() {
        var s = session("profile-test-one");
        var value = service.edit(
                s,
                new AccountService.EditProfile(
                        "测试买家", 1L, "13800000000", "FEMALE", java.time.LocalDate.of(2000, 2, 29)));
        assertThat(service.profile(s)).isEqualTo(value);
        assertThat(value.phone()).isEqualTo("13800000000");
        assertThat(value.birth_date()).isEqualTo(java.time.LocalDate.of(2000, 2, 29));
        assertThatThrownBy(() -> service.edit(s, new AccountService.EditProfile("测试", 2L, "bad", "FEMALE", null)))
                .isInstanceOf(Refused.class);
        assertThatThrownBy(() -> service.edit(s, new AccountService.EditProfile("测试", 2L, null, "INVALID", null)))
                .isInstanceOf(Refused.class);
        assertThatThrownBy(() -> service.edit(
                        s,
                        new AccountService.EditProfile(
                                "测试", 2L, null, null, java.time.LocalDate.now().plusDays(1))))
                .isInstanceOf(Refused.class);
        assertThat(service.profile(session("profile-test-two")).phone()).isNull();
    }

    @Test
    void nicknamePersistsWithoutChangingIdentityAndRejectsStaleEdits() {
        var s = session("profile-test-one");
        assertThat(service.edit(s, new AccountService.EditProfile("卡皮巴拉", 1L)).display_name())
                .isEqualTo("卡皮巴拉");
        assertThat(service.profile(s).version()).isEqualTo(2);
        assertThatThrownBy(() -> service.edit(s, new AccountService.EditProfile("旧页面", 1L)))
                .isInstanceOf(Refused.class);
        assertThat(jdbc.queryForObject(
                        "SELECT identity_version FROM identity_account WHERE username=?",
                        Long.class,
                        s.principal().subject()))
                .isEqualTo(1);
        assertThat(service.profile(session("profile-test-two")).display_name()).isEqualTo("测试买家");
    }

    @Test
    void addressOwnershipAndDefaultArePersisted() {
        var one = session("profile-test-one");
        var two = session("profile-test-two");
        var a = service.saveAddress(one, null, address(false, null));
        assertThat(a.is_default()).isTrue();
        var b = service.saveAddress(one, null, address(true, null));
        assertThat(service.addresses(one).stream()
                        .filter(AccountService.Address::is_default)
                        .count())
                .isEqualTo(1);
        assertThatThrownBy(() -> service.saveAddress(two, a.address_id(), address(true, a.version())))
                .isInstanceOf(Refused.class);
        assertThatThrownBy(() -> service.deleteAddress(two, a.address_id(), a.version()))
                .isInstanceOf(Refused.class);
        assertThatThrownBy(() -> service.deleteAddress(one, a.address_id(), a.version()))
                .isInstanceOf(Refused.class);
        service.deleteAddress(one, b.address_id(), b.version());
        assertThat(service.addresses(one)).hasSize(1);
        assertThat(service.addresses(one).getFirst().is_default()).isTrue();
    }

    @Test
    void shippingRequiresAnOwnedCurrentAddressAndFreezesItsContents() {
        var owner = session("profile-test-one");
        var a = service.saveAddress(owner, null, address(true, null));
        var selection = new com.resolveflow.shared.shopping.ShippingWire.Selection(a.address_id(), a.version());
        var frozen = service.shipping(owner, selection);
        assertThatThrownBy(() -> service.shipping(session("profile-test-two"), selection))
                .isInstanceOf(Refused.class);
        var changed = service.saveAddress(
                owner,
                a.address_id(),
                new AccountService.EditAddress("新收货人", "13000000001", "测试省", "测试市", "测试区", "新地址", true, a.version()));
        assertThatThrownBy(() -> service.shipping(owner, selection)).isInstanceOf(Refused.class);
        assertThat(frozen.recipient()).isEqualTo(a.recipient());
        service.deleteAddress(owner, changed.address_id(), changed.version());
        assertThatThrownBy(() -> service.shipping(
                        owner,
                        new com.resolveflow.shared.shopping.ShippingWire.Selection(
                                changed.address_id(), changed.version())))
                .isInstanceOf(Refused.class);
    }

    @Test
    void concurrentDefaultCreatesSerializeOnTheAccount() throws Exception {
        var s = session("profile-test-one");
        try (var pool = Executors.newFixedThreadPool(2)) {
            var a = pool.submit(() -> service.saveAddress(s, null, address(true, null)));
            var b = pool.submit(() -> service.saveAddress(s, null, address(true, null)));
            a.get();
            b.get();
        }
        assertThat(service.addresses(s)).hasSize(2);
        assertThat(service.addresses(s).stream()
                        .filter(AccountService.Address::is_default)
                        .count())
                .isEqualTo(1);
    }

    @Test
    void revokedSessionCannotWriteAndInvalidProfileDoesNotPersist() {
        var s = session("profile-test-one");
        assertThatThrownBy(() -> service.edit(s, new AccountService.EditProfile("\n", 1L)))
                .isInstanceOf(Refused.class);
        jdbc.update(
                "UPDATE identity_account SET identity_version=2 WHERE username=?",
                s.principal().subject());
        assertThatThrownBy(() -> service.edit(s, new AccountService.EditProfile("旧登录", 1L)))
                .isInstanceOf(Refused.class);
        assertThatThrownBy(() -> service.saveAddress(s, null, address(false, null)))
                .isInstanceOf(Refused.class);
        assertThat(service.addresses(s)).isEmpty();
    }
}
