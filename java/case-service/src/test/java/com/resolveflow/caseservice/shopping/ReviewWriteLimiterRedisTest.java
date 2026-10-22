package com.resolveflow.caseservice.shopping;

import static org.assertj.core.api.Assertions.*;

import com.resolveflow.shared.security.AuthenticatedPrincipal;
import com.resolveflow.shared.security.Role;
import io.micrometer.core.instrument.simple.SimpleMeterRegistry;
import java.time.Duration;
import java.util.UUID;
import java.util.concurrent.Executors;
import org.junit.jupiter.api.AfterAll;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.data.redis.connection.RedisStandaloneConfiguration;
import org.springframework.data.redis.connection.lettuce.LettuceClientConfiguration;
import org.springframework.data.redis.connection.lettuce.LettuceConnectionFactory;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.testcontainers.containers.GenericContainer;

class ReviewWriteLimiterRedisTest {
    static final GenericContainer<?> REDIS = new GenericContainer<>("redis:7.4-alpine").withExposedPorts(6379);

    static {
        REDIS.start();
    }

    @AfterAll
    static void stopRedis() {
        REDIS.stop();
    }

    private LettuceConnectionFactory connection;
    private StringRedisTemplate redis;

    @BeforeEach
    void connect() {
        connection = new LettuceConnectionFactory(
                new RedisStandaloneConfiguration(REDIS.getHost(), REDIS.getMappedPort(6379)),
                LettuceClientConfiguration.builder()
                        .commandTimeout(Duration.ofMillis(100))
                        .build());
        connection.afterPropertiesSet();
        redis = new StringRedisTemplate(connection);
        redis.afterPropertiesSet();
    }

    @AfterEach
    void disconnect() {
        connection.destroy();
    }

    private AuthenticatedPrincipal buyer() {
        return new AuthenticatedPrincipal("rate-" + UUID.randomUUID(), null, Role.CUSTOMER, null, "B-1");
    }

    @Test
    void seventhWriteIsRejectedButReplyAndOtherAccountRemainIndependent() {
        var limiter = new ReviewWriteLimiter(redis, new SimpleMeterRegistry(), true);
        var p = buyer();
        for (int i = 0; i < 6; i++) limiter.check(p, ReviewWriteLimiter.Action.WRITE);
        assertThatThrownBy(() -> limiter.check(p, ReviewWriteLimiter.Action.WRITE))
                .isInstanceOf(ReviewWriteLimiter.WriteLimited.class);
        limiter.check(p, ReviewWriteLimiter.Action.REPLY);
        limiter.check(buyer(), ReviewWriteLimiter.Action.WRITE);
        var keys = redis.keys("rf:reviews:write:v1:*");
        assertThat(keys).isNotEmpty();
        for (var key : keys) assertThat(redis.getExpire(key)).isBetween(1L, 60L);
    }

    @Test
    void twoInstancesAtomicallyShareOneAccountWindow() throws Exception {
        var first = new ReviewWriteLimiter(redis, new SimpleMeterRegistry(), true);
        var second = new ReviewWriteLimiter(redis, new SimpleMeterRegistry(), true);
        var p = buyer();
        try (var pool = Executors.newFixedThreadPool(12)) {
            var results = java.util.stream.IntStream.range(0, 12)
                    .mapToObj(i -> pool.submit(() -> {
                        try {
                            (i % 2 == 0 ? first : second).check(p, ReviewWriteLimiter.Action.WRITE);
                            return true;
                        } catch (ReviewWriteLimiter.WriteLimited limited) {
                            return false;
                        }
                    }))
                    .toList();
            int accepted = 0;
            for (var result : results) if (result.get()) accepted++;
            assertThat(accepted).isEqualTo(6);
        }
    }

    @Test
    void pausedRedisFailsClosedWithinCommandBound() throws Exception {
        redis.opsForValue().get("connection-ready");
        var limiter = new ReviewWriteLimiter(redis, new SimpleMeterRegistry(), true);
        try {
            REDIS.execInContainer("redis-cli", "CLIENT", "PAUSE", "2000");
            long started = System.nanoTime();
            assertThatThrownBy(() -> limiter.check(buyer(), ReviewWriteLimiter.Action.WRITE))
                    .isInstanceOf(ReviewWriteLimiter.WriteUnavailable.class);
            assertThat(Duration.ofNanos(System.nanoTime() - started)).isLessThan(Duration.ofMillis(1200));
        } finally {
            REDIS.execInContainer("redis-cli", "CLIENT", "UNPAUSE");
        }
    }
}
