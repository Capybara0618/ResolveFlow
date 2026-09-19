package com.resolveflow.caseservice.auth;

import com.resolveflow.shared.security.DemoAccounts;
import com.resolveflow.shared.security.JwtCodec;
import java.time.Clock;
import java.time.Duration;
import java.time.Instant;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;

/**
 * Wires the demonstration identity.
 *
 * <p>The signing secret is configuration with a local default, not a secret in source: the point of
 * the demonstration account is that the whole flow can be run and explained, and a "secret" committed
 * to a public repository would be a false claim of security. Any real deployment must supply
 * {@code resolveflow.identity.jwt.secret} (see docs/security-and-limits).
 */
@Configuration
public class IdentityConfiguration {

    @Bean
    JwtCodec jwtCodec(
            @Value("${resolveflow.identity.jwt.secret}") String secret,
            @Value("${resolveflow.identity.jwt.ttl-seconds:3600}") long ttlSeconds) {
        return new JwtCodec(secret, Duration.ofSeconds(ttlSeconds));
    }

    @Bean
    DemoAccounts demoAccounts(JwtCodec jwtCodec) {
        return new DemoAccounts(jwtCodec);
    }

    /** The clock is a bean so tests can move time without touching the codec. */
    @Bean
    Clock identityClock() {
        return Clock.systemUTC();
    }

    /** Now, per the injected clock; the login path never reads the wall clock directly. */
    static Instant now(Clock clock) {
        return Instant.now(clock);
    }
}
