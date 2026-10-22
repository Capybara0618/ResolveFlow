package com.resolveflow.commerce.catalog;

import static org.assertj.core.api.Assertions.*;

import com.resolveflow.commerce.CommerceDatabaseTest;
import com.resolveflow.shared.shopping.CheckoutWire.PayCommand;
import com.resolveflow.shared.shopping.ProductReviewWire.*;
import com.resolveflow.shared.shopping.ShoppingWire.*;
import io.micrometer.core.instrument.simple.SimpleMeterRegistry;
import java.time.Duration;
import java.util.UUID;
import org.junit.jupiter.api.AfterAll;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.data.redis.connection.RedisStandaloneConfiguration;
import org.springframework.data.redis.connection.lettuce.LettuceClientConfiguration;
import org.springframework.data.redis.connection.lettuce.LettuceConnectionFactory;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.jdbc.core.JdbcTemplate;
import org.testcontainers.containers.GenericContainer;
import tools.jackson.databind.ObjectMapper;

class ProductReviewCacheIntegrationTest extends CommerceDatabaseTest {
    private static final GenericContainer<?> REDIS = new GenericContainer<>("redis:7.4-alpine").withExposedPorts(6379);

    static {
        REDIS.start();
    }

    @AfterAll
    static void stopRedis() {
        REDIS.stop();
    }

    @Autowired
    ProductReviewService reviews;

    @Autowired
    ShoppingService shop;

    @Autowired
    CheckoutPayments payments;

    @Autowired
    JdbcTemplate jdbc;

    private LettuceConnectionFactory connection(int port) {
        var config = new RedisStandaloneConfiguration(REDIS.getHost(), port);
        var c = new LettuceConnectionFactory(
                config,
                LettuceClientConfiguration.builder()
                        .commandTimeout(Duration.ofMillis(100))
                        .build());
        c.afterPropertiesSet();
        return c;
    }

    private StringRedisTemplate template(LettuceConnectionFactory c) {
        var t = new StringRedisTemplate(c);
        t.afterPropertiesSet();
        return t;
    }

    @Test
    void committedEpochPreventsLateOldCachePopulationFromOverwritingNewRating() {
        var connection = connection(REDIS.getMappedPort(6379));
        try {
            var redis = template(connection);
            var metrics = new SimpleMeterRegistry();
            var json = new ObjectMapper();
            var cache = new ProductReviewReadCache(reviews, redis, json, metrics, true);
            String customer = "REVIEW-REDIS";
            var d = shop.create(new DraftCommand(
                    "M-1001", customer, UUID.randomUUID().toString(), new DraftRequest("SKU-1001-BLACK", 1, 1L)));
            var p = payments.pay(
                    d.draftId(),
                    new PayCommand("M-1001", customer, UUID.randomUUID().toString()));
            jdbc.update(
                    "UPDATE shipment SET status='DELIVERED',carrier_conclusion='DELIVERED',source_version=2 WHERE line_id=?",
                    p.lineId());
            var r = reviews.save(p.lineId(), new Command("M-1001", customer, new Write(5L, "original", 0L)));
            long oldEpoch = reviews.publicEpoch("P-1001");
            var old = cache.read("P-1001", null, 10);
            assertThat(cache.read("P-1001", null, 10)).isEqualTo(old);
            reviews.save(p.lineId(), new Command("M-1001", customer, new Write(1L, "updated", r.version())));
            var updated = cache.read("P-1001", null, 10);
            redis.opsForValue()
                    .set(
                            "rf:reviews:first:v1:P-1001:" + oldEpoch,
                            json.writeValueAsString(old),
                            Duration.ofSeconds(30));
            assertThat(cache.read("P-1001", null, 10)).isEqualTo(updated);
            assertThat(updated.items())
                    .anyMatch(i -> i.reviewId() == r.reviewId()
                            && i.rating() == 1
                            && i.body().equals("updated"));
            assertThat(metrics.counter("resolveflow.product_reviews.cache", "outcome", "hit")
                            .count())
                    .isEqualTo(2);
            assertThat(redis.getExpire("rf:reviews:first:v1:P-1001:" + oldEpoch))
                    .isBetween(1L, 30L);
        } finally {
            connection.destroy();
        }
    }

    @Test
    void stalledRedisCommandsTimeOutAndReturnAuthoritativeDatabaseSnapshot() throws Exception {
        var connection = connection(REDIS.getMappedPort(6379));
        try {
            var redis = template(connection);
            var metrics = new SimpleMeterRegistry();
            redis.opsForValue().get("connection-ready");
            assertThat(REDIS.execInContainer("redis-cli", "CLIENT", "PAUSE", "2000")
                            .getExitCode())
                    .isZero();
            long started = System.nanoTime();
            var result = new ProductReviewReadCache(reviews, redis, new ObjectMapper(), metrics, true)
                    .read("P-2001", null, 10);
            assertThat(Duration.ofNanos(System.nanoTime() - started)).isLessThan(Duration.ofMillis(1200));
            assertThat(result.items()).isEmpty();
            assertThat(metrics.counter("resolveflow.product_reviews.cache", "outcome", "error")
                            .count())
                    .isEqualTo(1);
        } finally {
            REDIS.execInContainer("redis-cli", "CLIENT", "UNPAUSE");
            connection.destroy();
        }
    }

    @Test
    void corruptPublicCacheFallsBackToActualEmptyProduct() {
        var connection = connection(REDIS.getMappedPort(6379));
        try {
            var redis = template(connection);
            var metrics = new SimpleMeterRegistry();
            redis.opsForValue()
                    .set(
                            "rf:reviews:first:v1:P-2002:" + reviews.publicEpoch("P-2002"),
                            "not-json",
                            Duration.ofSeconds(30));
            var cache = new ProductReviewReadCache(reviews, redis, new ObjectMapper(), metrics, true);
            assertThat(cache.read("P-2002", null, 10).items()).isEmpty();
            assertThat(metrics.counter("resolveflow.product_reviews.cache", "outcome", "error")
                            .count())
                    .isEqualTo(1);
        } finally {
            connection.destroy();
        }
    }
}
