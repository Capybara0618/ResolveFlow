package com.resolveflow.commerce.publicapi;

import com.resolveflow.shared.security.AuthenticatedPrincipal;
import io.micrometer.core.instrument.MeterRegistry;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.util.HexFormat;
import java.util.List;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.data.redis.core.script.DefaultRedisScript;
import org.springframework.stereotype.Component;

@Component
public class ReviewWriteLimiter {
    public enum Action {
        WRITE,
        REPLY
    }

    private static final DefaultRedisScript<Long> WINDOW = new DefaultRedisScript<>(
            "local n=redis.call('INCR',KEYS[1]); if n==1 or redis.call('TTL',KEYS[1])<0 then redis.call('EXPIRE',KEYS[1],60) end; return n",
            Long.class);
    private final StringRedisTemplate redis;
    private final MeterRegistry metrics;
    private final boolean enabled;

    public ReviewWriteLimiter(
            StringRedisTemplate redis,
            MeterRegistry metrics,
            @Value("${resolveflow.product-reviews.rate-limit-enabled:false}") boolean enabled) {
        this.redis = redis;
        this.metrics = metrics;
        this.enabled = enabled;
    }

    public void check(AuthenticatedPrincipal principal, Action action) {
        if (principal == null || action == null) throw new IllegalArgumentException("authenticated action required");
        if (!enabled) return;
        String key;
        try {
            key = "rf:reviews:write:v1:"
                    + HexFormat.of()
                            .formatHex(MessageDigest.getInstance("SHA-256")
                                    .digest((principal.subject() + "\n" + action.name())
                                            .getBytes(StandardCharsets.UTF_8)));
        } catch (NoSuchAlgorithmException impossible) {
            throw new IllegalStateException(impossible);
        }
        Long count;
        try {
            count = redis.execute(WINDOW, List.of(key));
        } catch (RuntimeException unavailable) {
            metrics.counter("resolveflow.product_reviews.writes", "outcome", "unavailable")
                    .increment();
            throw new WriteUnavailable();
        }
        if (count == null || count < 1) throw new WriteUnavailable();
        if (count > 6) {
            metrics.counter("resolveflow.product_reviews.writes", "outcome", "limited")
                    .increment();
            throw new WriteLimited();
        }
        metrics.counter("resolveflow.product_reviews.writes", "outcome", "allowed")
                .increment();
    }

    public static class WriteLimited extends RuntimeException {
        private static final long serialVersionUID = 1L;
    }

    public static class WriteUnavailable extends RuntimeException {
        private static final long serialVersionUID = 1L;
    }
}
