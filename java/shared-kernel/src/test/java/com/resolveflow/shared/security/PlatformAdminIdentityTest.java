package com.resolveflow.shared.security;

import static org.assertj.core.api.Assertions.*;

import java.time.Duration;
import java.time.Instant;
import org.junit.jupiter.api.Test;

class PlatformAdminIdentityTest {
    @Test
    void platformAdminHasNoTenantAndCannotPretendToBeBuyerOrStaff() {
        var role = Role.valueOf("PLATFORM_ADMIN");
        var principal = new AuthenticatedPrincipal("platform", null, role, null);
        assertThat(role.isMerchantStaff()).isFalse();
        var codec = new JwtCodec("platform-test-secret-for-local", Duration.ofMinutes(10));
        var now = Instant.parse("2026-10-03T00:00:00Z");
        assertThat(codec.verifyAsUser(codec.issue(principal, 2, now), now)).isEqualTo(principal);
        assertThatThrownBy(() -> new AuthenticatedPrincipal("platform", "M-1001", role, null))
                .isInstanceOf(IllegalArgumentException.class);
        assertThatThrownBy(() -> new AuthenticatedPrincipal("platform", null, role, "B-1"))
                .isInstanceOf(IllegalArgumentException.class);
    }
}
