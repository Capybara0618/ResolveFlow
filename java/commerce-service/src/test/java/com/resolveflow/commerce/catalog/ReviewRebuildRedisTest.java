package com.resolveflow.commerce.catalog;

import static org.assertj.core.api.Assertions.*;

import java.util.concurrent.TimeUnit;
import org.junit.jupiter.api.Test;
import org.redisson.Redisson;
import org.springframework.data.redis.connection.RedisStandaloneConfiguration;
import org.springframework.data.redis.connection.lettuce.LettuceConnectionFactory;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.testcontainers.containers.GenericContainer;

class ReviewRebuildRedisTest {
    @Test
    void twoClientsShareExplicitLeaseAndCannotReleaseAnotherOwner() throws Exception {
        try (var redis = new GenericContainer<>("redis:7.4-alpine").withExposedPorts(6379)) {
            redis.start();
            String address = "redis://" + redis.getHost() + ":" + redis.getMappedPort(6379);
            var config = ReviewRebuildConfiguration.configuration(address, "", "", 0);
            assertThat(config.isLazyInitialization()).isTrue();
            assertThat(config.useSingleServer().getRetryAttempts()).isZero();
            var first = Redisson.create(config);
            var second = Redisson.create(ReviewRebuildConfiguration.configuration(address, "", "", 0));
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
                var a = first.getLock("owned-test-lock");
                var b = second.getLock("owned-test-lock");
                assertThat(a.tryLock(100, 2000, TimeUnit.MILLISECONDS)).isTrue();
                long started = System.nanoTime();
                assertThat(b.tryLock(100, 2000, TimeUnit.MILLISECONDS)).isFalse();
                assertThat(TimeUnit.NANOSECONDS.toMillis(System.nanoTime() - started))
                        .isLessThan(1200);
                assertThat(a.remainTimeToLive()).isBetween(1L, 2000L);
                assertThat(b.tryLock(3000, 2000, TimeUnit.MILLISECONDS)).isTrue();
                assertThat(a.isHeldByCurrentThread()).isFalse();
                assertThatThrownBy(a::unlock).isInstanceOf(IllegalMonitorStateException.class);
                assertThat(b.isHeldByCurrentThread()).isTrue();
                b.unlock();
                assertThat(template.opsForValue().get("coexist")).isEqualTo("unchanged");
            } finally {
                connection.destroy();
                first.shutdown(0, 1, TimeUnit.SECONDS);
                second.shutdown(0, 1, TimeUnit.SECONDS);
            }
        }
    }
}
