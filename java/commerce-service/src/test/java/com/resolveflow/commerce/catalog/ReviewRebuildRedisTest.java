package com.resolveflow.commerce.catalog;

import static org.assertj.core.api.Assertions.*;

import io.micrometer.core.instrument.simple.SimpleMeterRegistry;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.Executors;
import java.util.concurrent.TimeUnit;
import org.junit.jupiter.api.Test;
import org.redisson.Redisson;
import org.springframework.data.redis.connection.RedisStandaloneConfiguration;
import org.springframework.data.redis.connection.lettuce.LettuceConnectionFactory;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.testcontainers.containers.GenericContainer;

class ReviewRebuildRedisTest {
    @Test
    void watchdogKeepsLongRebuildExclusiveAndNormalCompletionReleasesLock() throws Exception {
        try (var redis = new GenericContainer<>("redis:7.4-alpine").withExposedPorts(6379)) {
            redis.start();
            String address = "redis://" + redis.getHost() + ":" + redis.getMappedPort(6379);
            var config = ReviewRebuildConfiguration.configuration(address, "", "", 0);
            assertThat(config.isLazyInitialization()).isTrue();
            assertThat(config.useSingleServer().getRetryAttempts()).isZero();
            assertThat(config.getLockWatchdogTimeout()).isEqualTo(30000);
            // Shorten only this isolated test's renewal window; production keeps the 30s default.
            config.setLockWatchdogTimeout(1500);
            var first = Redisson.create(config);
            var second = Redisson.create(
                    ReviewRebuildConfiguration.configuration(address, "", "", 0).setLockWatchdogTimeout(1500));
            var connection = new LettuceConnectionFactory(
                    new RedisStandaloneConfiguration(redis.getHost(), redis.getMappedPort(6379)));
            connection.afterPropertiesSet();
            var template = new StringRedisTemplate(connection);
            template.afterPropertiesSet();
            try {
                template.opsForValue().set("coexist", "unchanged");
                assertThat(first.getBucket("coexist", org.redisson.client.codec.StringCodec.INSTANCE)
                                .get())
                        .isEqualTo("unchanged");
                assertThat(second.getBucket("coexist", org.redisson.client.codec.StringCodec.INSTANCE)
                                .get())
                        .isEqualTo("unchanged");
                var entered = new CountDownLatch(1);
                var release = new CountDownLatch(1);
                var rebuild = new ReviewRebuildLock(first, new SimpleMeterRegistry());
                var other = second.getLock("owned-test:rebuild");
                try (var pool = Executors.newSingleThreadExecutor()) {
                    var result = pool.submit(() -> rebuild.rebuild(
                            "owned-test",
                            owns -> {
                                entered.countDown();
                                try {
                                    if (!release.await(10, TimeUnit.SECONDS))
                                        throw new AssertionError("rebuild gate timed out");
                                } catch (InterruptedException interrupted) {
                                    Thread.currentThread().interrupt();
                                    throw new IllegalStateException(interrupted);
                                }
                                assertThat(owns.getAsBoolean()).isTrue();
                                return "rebuilt";
                            },
                            () -> "unexpected waiter",
                            () -> "unexpected fallback"));
                    try {
                        assertThat(entered.await(5, TimeUnit.SECONDS)).isTrue();
                        // Exceed both the shortened watchdog window and the former fixed 2s lease.
                        Thread.sleep(3100);
                        assertThat(other.remainTimeToLive()).isBetween(1L, 1500L);
                        assertThat(other.tryLock(100, TimeUnit.MILLISECONDS)).isFalse();
                        assertThatThrownBy(other::unlock).isInstanceOf(IllegalMonitorStateException.class);
                    } finally {
                        release.countDown();
                    }
                    assertThat(result.get(5, TimeUnit.SECONDS)).isEqualTo("rebuilt");
                }
                assertThat(other.tryLock(100, TimeUnit.MILLISECONDS)).isTrue();
                other.unlock();
                assertThat(template.opsForValue().get("coexist")).isEqualTo("unchanged");
                assertThatThrownBy(() -> rebuild.rebuild(
                                "failed-test",
                                owns -> {
                                    throw new IllegalArgumentException("database failed");
                                },
                                () -> "unexpected waiter",
                                () -> "unexpected fallback"))
                        .isInstanceOf(IllegalArgumentException.class);
                var afterFailure = second.getLock("failed-test:rebuild");
                assertThat(afterFailure.tryLock(100, TimeUnit.MILLISECONDS)).isTrue();
                afterFailure.unlock();
            } finally {
                connection.destroy();
                first.shutdown(0, 1, TimeUnit.SECONDS);
                second.shutdown(0, 1, TimeUnit.SECONDS);
            }
        }
    }

    @Test
    void stoppedClientStopsRenewingAndAnotherClientCanAcquireAfterExpiry() throws Exception {
        try (var redis = new GenericContainer<>("redis:7.4-alpine").withExposedPorts(6379)) {
            redis.start();
            String address = "redis://" + redis.getHost() + ":" + redis.getMappedPort(6379);
            var first = Redisson.create(
                    ReviewRebuildConfiguration.configuration(address, "", "", 0).setLockWatchdogTimeout(1500));
            var second = Redisson.create(
                    ReviewRebuildConfiguration.configuration(address, "", "", 0).setLockWatchdogTimeout(1500));
            try {
                assertThat(first.getLock("stopped-client").tryLock(100, TimeUnit.MILLISECONDS))
                        .isTrue();
                var next = second.getLock("stopped-client");
                assertThat(next.tryLock(100, TimeUnit.MILLISECONDS)).isFalse();
                first.shutdown(0, 1, TimeUnit.SECONDS);
                assertThat(next.tryLock(5000, TimeUnit.MILLISECONDS)).isTrue();
                assertThat(next.isHeldByCurrentThread()).isTrue();
                next.unlock();
            } finally {
                if (!first.isShutdown()) first.shutdown(0, 1, TimeUnit.SECONDS);
                second.shutdown(0, 1, TimeUnit.SECONDS);
            }
        }
    }
}
