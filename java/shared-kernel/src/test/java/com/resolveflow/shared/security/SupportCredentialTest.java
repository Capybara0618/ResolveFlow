package com.resolveflow.shared.security;

import static org.assertj.core.api.Assertions.*;

import java.time.Duration;
import java.time.Instant;
import org.junit.jupiter.api.Test;

class SupportCredentialTest {
    @Test
    void progressCredentialCannotReadFactsAndReadCredentialCannotWriteProgress() {
        var codec = new JwtCodec("support-test-secret-for-local", Duration.ofMinutes(10));
        var now = Instant.parse("2026-10-23T00:00:00Z");
        var bound = new JwtCodec.SupportCredential("run", "conversation", 2, 1, "M-A", "C-A", "line");
        var progress = codec.issueSupportProgressCredential(bound, now);
        assertThat(codec.verifySupportProgressCredential(progress, now)).isEqualTo(bound);
        assertThat(codec.verifyAsService(progress, now).scopes()).containsExactly("support:progress");
        assertThatThrownBy(() -> codec.verifySupportCredential(progress, now))
                .isInstanceOf(JwtCodec.TokenException.class);
        assertThatThrownBy(() -> codec.verifySupportProgressCredential(codec.issueSupportCredential(bound, now), now))
                .isInstanceOf(JwtCodec.TokenException.class);
    }

    @Test
    void consultationHasNoCaseOrCommerceScopeAndExpiresWithoutRenewal() {
        var codec = new JwtCodec("support-test-secret-for-local", Duration.ofMinutes(10));
        var now = Instant.parse("2026-10-20T00:00:00Z");
        var bound = new JwtCodec.SupportCredential("run", "conversation", 2, 1, "M-A", "C-A", "line");
        String token = codec.issueSupportCredential(bound, now);
        assertThat(codec.verifySupportCredential(token, now)).isEqualTo(bound);
        var service = codec.verifyAsService(token, now);
        assertThat(service.scopes()).containsExactly("support:read");
        assertThat(service.hasScope(ServiceScopes.COMMERCE_READ)).isFalse();
        assertThatThrownBy(() -> codec.verifySupportCredential(token, now.plusSeconds(151)))
                .isInstanceOf(JwtCodec.TokenException.class);
        var plain = codec.issueServiceToken("agent-service", now);
        assertThatThrownBy(() -> codec.verifySupportCredential(plain, now)).isInstanceOf(JwtCodec.TokenException.class);
    }
}
