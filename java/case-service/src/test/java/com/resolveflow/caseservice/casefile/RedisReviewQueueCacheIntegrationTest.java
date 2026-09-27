package com.resolveflow.caseservice.casefile;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.when;

import com.resolveflow.shared.security.AuthenticatedPrincipal;
import com.resolveflow.shared.security.Role;
import io.micrometer.core.instrument.simple.SimpleMeterRegistry;
import java.net.ServerSocket;
import java.time.Duration;
import java.util.List;
import java.util.UUID;
import java.util.concurrent.Callable;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.Executors;
import java.util.concurrent.Future;
import java.util.concurrent.TimeUnit;
import org.junit.jupiter.api.AfterAll;
import org.junit.jupiter.api.Test;
import org.springframework.data.redis.connection.RedisStandaloneConfiguration;
import org.springframework.data.redis.connection.lettuce.LettuceClientConfiguration;
import org.springframework.data.redis.connection.lettuce.LettuceConnectionFactory;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.testcontainers.containers.GenericContainer;
import tools.jackson.databind.ObjectMapper;

/** Actual Redis, namespaced to this test; never flushes a shared server. */
class RedisReviewQueueCacheIntegrationTest {

    static final GenericContainer<?> REDIS = new GenericContainer<>("redis:7.4-alpine").withExposedPorts(6379);

    static {
        REDIS.start();
    }

    @AfterAll
    static void stopRedis() {
        REDIS.stop();
    }

    @Test
    void hitMissScopeUpdateAndExpiryAreRealRedisOperations() throws Exception {
        RedisStandaloneConfiguration config =
                new RedisStandaloneConfiguration(REDIS.getHost(), REDIS.getMappedPort(6379));
        LettuceConnectionFactory connection = new LettuceConnectionFactory(config);
        connection.afterPropertiesSet();
        try {
            StringRedisTemplate template = new StringRedisTemplate(connection);
            template.afterPropertiesSet();
            RedisReviewQueueCache cache =
                    new RedisReviewQueueCache(template, new ObjectMapper(), "rf:c11:test:" + UUID.randomUUID());
            ReviewQueueService.Page first = new ReviewQueueService.Page(List.of(), null, 20);
            ReviewQueueService.Page updated = new ReviewQueueService.Page(List.of(), "next", 20);
            assertThat(cache.find("M-1001", null, 20)).isEmpty();
            cache.store("M-1001", null, 20, first);
            assertThat(cache.find("M-1001", null, 20)).contains(first);
            assertThat(cache.find("M-2002", null, 20)).isEmpty();
            assertThat(cache.find("M-1001", "other-cursor", 20)).isEmpty();
            cache.store("M-1001", null, 20, updated);
            assertThat(cache.find("M-1001", null, 20)).contains(updated);
            Thread.sleep(RedisReviewQueueCache.TTL.plusMillis(150));
            assertThat(cache.find("M-1001", null, 20)).isEmpty();
        } finally {
            connection.destroy();
        }
    }

    @Test
    void disconnectedRedisFailsWithinCommandBound() throws Exception {
        int unusedPort;
        try (ServerSocket reserved = new ServerSocket(0)) {
            unusedPort = reserved.getLocalPort();
        }
        LettuceConnectionFactory connection = boundedConnection(unusedPort);
        try {
            RedisReviewQueueCache cache = cache(connection);
            long started = System.nanoTime();
            assertThatThrownBy(() -> cache.find("M-1001", null, 20)).isInstanceOf(RuntimeException.class);
            assertThat(Duration.ofNanos(System.nanoTime() - started)).isLessThan(Duration.ofSeconds(2));
        } finally {
            connection.destroy();
        }
    }

    @Test
    void pausedRedisTimesOutRatherThanWaitingForServer() throws Exception {
        LettuceConnectionFactory connection = boundedConnection(REDIS.getMappedPort(6379));
        try {
            RedisReviewQueueCache cache = cache(connection);
            assertThat(cache.find("M-1001", null, 20)).isEmpty();
            CaseRepository repository = mock(CaseRepository.class);
            when(repository.findReviewQueue("M-1001", null, null, 21)).thenReturn(List.of());
            SimpleMeterRegistry metrics = new SimpleMeterRegistry();
            ReviewQueueService service = new ReviewQueueService(repository, cache, metrics, true);
            assertThat(REDIS.execInContainer("redis-cli", "CLIENT", "PAUSE", "1000")
                            .getExitCode())
                    .isZero();
            long started = System.nanoTime();
            assertThatThrownBy(() -> cache.find("M-1001", null, 20)).isInstanceOf(RuntimeException.class);
            assertThat(Duration.ofNanos(System.nanoTime() - started)).isLessThan(Duration.ofMillis(800));
            assertThat(service.list(new AuthenticatedPrincipal("staff", "M-1001", Role.REVIEWER, null), null, null)
                            .items())
                    .isEmpty();
            assertThat(metrics.counter("resolveflow.review.cache", "outcome", "error")
                            .count())
                    .isEqualTo(1);
            assertThat(metrics.counter("resolveflow.review.database.queries").count())
                    .isEqualTo(1);
        } finally {
            REDIS.execInContainer("redis-cli", "CLIENT", "UNPAUSE");
            connection.destroy();
        }
    }

    @Test
    void expiredHotKeyUsesRealRedisAndBoundsConcurrentDatabaseFallback() throws Exception {
        LettuceConnectionFactory connection = boundedConnection(REDIS.getMappedPort(6379));
        var pool = Executors.newFixedThreadPool(12);
        CountDownLatch release = new CountDownLatch(1);
        try {
            RedisReviewQueueCache cache = cache(connection);
            cache.store("M-1001", null, 20, new ReviewQueueService.Page(List.of(), null, 20));
            Thread.sleep(RedisReviewQueueCache.TTL.plusMillis(500));
            assertThat(cache.find("M-1001", null, 20)).isEmpty();
            CaseRepository repository = mock(CaseRepository.class);
            CountDownLatch reading = new CountDownLatch(8);
            CountDownLatch rejected = new CountDownLatch(4);
            when(repository.findReviewQueue("M-1001", null, null, 21)).thenAnswer(invocation -> {
                reading.countDown();
                if (!release.await(5, TimeUnit.SECONDS)) {
                    throw new AssertionError("database fixture timed out");
                }
                return List.of();
            });
            SimpleMeterRegistry metrics = new SimpleMeterRegistry();
            ReviewQueueService service = new ReviewQueueService(repository, cache, metrics, true);
            AuthenticatedPrincipal staff = new AuthenticatedPrincipal("staff", "M-1001", Role.REVIEWER, null);
            CountDownLatch start = new CountDownLatch(1);
            List<Future<Boolean>> results = java.util.stream.IntStream.range(0, 12)
                    .<Callable<Boolean>>mapToObj(index -> () -> {
                        start.await();
                        try {
                            service.list(staff, null, null);
                            return true;
                        } catch (ReviewQueueService.ReviewQueueBusyException busy) {
                            rejected.countDown();
                            return false;
                        }
                    })
                    .map(pool::submit)
                    .toList();
            start.countDown();
            assertThat(reading.await(3, TimeUnit.SECONDS)).isTrue();
            assertThat(rejected.await(3, TimeUnit.SECONDS)).isTrue();
            release.countDown();
            int accepted = 0;
            for (Future<Boolean> result : results) {
                accepted += result.get(3, TimeUnit.SECONDS) ? 1 : 0;
            }
            assertThat(accepted).isEqualTo(8);
            assertThat(metrics.counter("resolveflow.review.fallback", "outcome", "rejected")
                            .count())
                    .isEqualTo(4);
            assertThat(metrics.counter("resolveflow.review.database.queries").count())
                    .isEqualTo(8);
        } finally {
            release.countDown();
            pool.shutdownNow();
            connection.destroy();
        }
    }

    private static LettuceConnectionFactory boundedConnection(int port) {
        RedisStandaloneConfiguration server = new RedisStandaloneConfiguration(REDIS.getHost(), port);
        LettuceClientConfiguration client = LettuceClientConfiguration.builder()
                .commandTimeout(Duration.ofMillis(100))
                .build();
        LettuceConnectionFactory connection = new LettuceConnectionFactory(server, client);
        connection.afterPropertiesSet();
        return connection;
    }

    private static RedisReviewQueueCache cache(LettuceConnectionFactory connection) {
        StringRedisTemplate template = new StringRedisTemplate(connection);
        template.afterPropertiesSet();
        return new RedisReviewQueueCache(template, new ObjectMapper(), "rf:c11:fault:" + UUID.randomUUID());
    }
}
