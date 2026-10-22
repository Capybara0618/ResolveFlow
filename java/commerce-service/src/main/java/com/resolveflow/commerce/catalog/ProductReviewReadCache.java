package com.resolveflow.commerce.catalog;

import com.resolveflow.shared.shopping.ProductReviewWire.Page;
import io.micrometer.core.instrument.MeterRegistry;
import java.time.Duration;
import java.util.concurrent.Semaphore;
import java.util.concurrent.TimeUnit;
import java.util.function.Supplier;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.stereotype.Service;
import tools.jackson.databind.ObjectMapper;

@Service
public class ProductReviewReadCache {
    private final ProductReviewService reviews;
    private final StringRedisTemplate redis;
    private final ObjectMapper json;
    private final MeterRegistry metrics;
    private final boolean enabled;
    private final Semaphore databasePermits = new Semaphore(8, true);

    public ProductReviewReadCache(
            ProductReviewService reviews,
            StringRedisTemplate redis,
            ObjectMapper json,
            MeterRegistry metrics,
            @Value("${resolveflow.product-reviews.cache-enabled:false}") boolean enabled) {
        this.reviews = reviews;
        this.redis = redis;
        this.json = json;
        this.metrics = metrics;
        this.enabled = enabled;
    }

    private <T> T database(Supplier<T> read) {
        boolean acquired = false;
        try {
            acquired = databasePermits.tryAcquire(100, TimeUnit.MILLISECONDS);
            if (!acquired) {
                metrics.counter("resolveflow.product_reviews.fallback", "outcome", "rejected")
                        .increment();
                throw new ReadBusy();
            }
            metrics.counter("resolveflow.product_reviews.database.reads").increment();
            return read.get();
        } catch (InterruptedException e) {
            Thread.currentThread().interrupt();
            throw new ReadBusy();
        } finally {
            if (acquired) databasePermits.release();
        }
    }

    public Page read(String product, Long before, Integer limit) {
        int size = ProductReviewService.limit(before, limit);
        if (!enabled || before != null || size != 10) return database(() -> reviews.publicPage(product, before, size));
        long epoch = database(() -> reviews.publicEpoch(product));
        String key = "rf:reviews:first:v1:" + product + ":" + epoch;
        try {
            var value = redis.opsForValue().get(key);
            if (value != null) {
                var page = json.readValue(value, Page.class);
                if (page.summary() == null || page.items().stream().anyMatch(r -> !product.equals(r.productId())))
                    throw new IllegalStateException("invalid public cache");
                metrics.counter("resolveflow.product_reviews.cache", "outcome", "hit")
                        .increment();
                return page;
            }
            metrics.counter("resolveflow.product_reviews.cache", "outcome", "miss")
                    .increment();
        } catch (RuntimeException unavailable) {
            metrics.counter("resolveflow.product_reviews.cache", "outcome", "error")
                    .increment();
        }
        var result = database(() -> reviews.publicPage(product, null, size));
        try {
            redis.opsForValue().set(key, json.writeValueAsString(result), Duration.ofSeconds(30));
        } catch (RuntimeException unavailable) {
            metrics.counter("resolveflow.product_reviews.cache.write", "outcome", "error")
                    .increment();
        }
        return result;
    }

    public static class ReadBusy extends RuntimeException {
        private static final long serialVersionUID = 1L;
    }
}
