package com.resolveflow.commerce.catalog;

import com.resolveflow.shared.shopping.ProductReviewWire.Page;
import io.micrometer.core.instrument.MeterRegistry;
import java.time.Duration;
import java.time.Instant;
import java.util.UUID;
import java.util.concurrent.Semaphore;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicInteger;
import java.util.function.BooleanSupplier;
import java.util.function.Supplier;
import org.redisson.api.RedissonClient;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.ObjectProvider;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.stereotype.Service;
import tools.jackson.databind.ObjectMapper;

@Service
public class ProductReviewReadCache {
    private static final Logger LOG = LoggerFactory.getLogger(ProductReviewReadCache.class);
    private final ProductReviewService reviews;
    private final PublicCatalogCacheStore cache;
    private final ObjectMapper json;
    private final MeterRegistry metrics;
    private final boolean enabled;
    private final ReviewRebuildLock lock;
    private final Semaphore databasePermits = new Semaphore(8, true);
    private final AtomicInteger inflight = new AtomicInteger(), peak = new AtomicInteger();
    private final AtomicInteger rebuilding = new AtomicInteger(), rebuildPeak = new AtomicInteger();

    public ProductReviewReadCache(
            ProductReviewService reviews,
            StringRedisTemplate redis,
            ObjectMapper json,
            MeterRegistry metrics,
            boolean enabled) {
        this(reviews, redis, json, metrics, enabled, (ReviewRebuildLock) null, "rf:reviews:first:v1");
    }

    @Autowired
    public ProductReviewReadCache(
            ProductReviewService reviews,
            StringRedisTemplate redis,
            ObjectMapper json,
            MeterRegistry metrics,
            @Value("${resolveflow.product-reviews.cache-enabled:false}") boolean enabled,
            ObjectProvider<RedissonClient> clients,
            @Value("${resolveflow.product-reviews.cache-namespace:rf:reviews:first:v1}") String namespace) {
        this(
                reviews,
                redis,
                json,
                metrics,
                enabled,
                clients.getIfAvailable() == null ? null : new ReviewRebuildLock(clients.getObject(), metrics),
                namespace);
    }

    ProductReviewReadCache(
            ProductReviewService reviews,
            StringRedisTemplate redis,
            ObjectMapper json,
            MeterRegistry metrics,
            boolean enabled,
            ReviewRebuildLock lock,
            String namespace) {
        if (namespace == null || !namespace.matches("[A-Za-z0-9:_-]{1,120}"))
            throw new IllegalArgumentException("invalid review cache namespace");
        this.reviews = reviews;
        this.cache = new PublicCatalogCacheStore(redis, json, namespace);
        this.json = json;
        this.metrics = metrics;
        this.enabled = enabled;
        this.lock = lock;
        metrics.gauge("resolveflow.product_reviews.database.inflight", inflight);
        metrics.gauge("resolveflow.product_reviews.database.peak", peak);
        metrics.gauge("resolveflow.product_reviews.rebuild.inflight", rebuilding);
        metrics.gauge("resolveflow.product_reviews.rebuild.peak", rebuildPeak);
    }

    private <T> T database(String operation, Supplier<T> read) {
        boolean acquired = false;
        try {
            acquired = databasePermits.tryAcquire(100, TimeUnit.MILLISECONDS);
            if (!acquired) {
                metrics.counter("resolveflow.product_reviews.fallback", "outcome", "rejected")
                        .increment();
                throw new ReadBusy();
            }
            int active = inflight.incrementAndGet();
            peak.accumulateAndGet(active, Math::max);
            metrics.counter("resolveflow.product_reviews.database.reads").increment();
            metrics.counter("resolveflow.product_reviews.database.calls", "operation", operation)
                    .increment();
            return read.get();
        } catch (InterruptedException interrupted) {
            Thread.currentThread().interrupt();
            throw new ReadBusy();
        } finally {
            if (acquired) {
                inflight.decrementAndGet();
                databasePermits.release();
            }
        }
    }

    private PublicCatalogCacheStore.Snapshot snapshot(String key, String product) {
        try {
            return cache.read(key, product);
        } catch (RuntimeException unavailable) {
            metrics.counter("resolveflow.product_reviews.cache", "outcome", "error")
                    .increment();
            throw new CacheUnavailable();
        }
    }

    private Page cached(PublicCatalogCacheStore.Snapshot snapshot, String product, String outcome) {
        try {
            String value = snapshot.value();
            if (value == null) return null;
            var page = json.readValue(value, Page.class);
            if (page.summary() == null || page.items().stream().anyMatch(row -> !product.equals(row.productId())))
                throw new IllegalStateException("invalid public cache");
            metrics.counter("resolveflow.product_reviews.cache", "outcome", outcome)
                    .increment();
            return page;
        } catch (RuntimeException unavailable) {
            metrics.counter("resolveflow.product_reviews.cache", "outcome", "error")
                    .increment();
            throw new CacheUnavailable();
        }
    }

    private Page load(
            String key, String product, int size, BooleanSupplier owns, PublicCatalogCacheStore.Snapshot snapshot) {
        String trace = UUID.randomUUID().toString();
        Page result = database("page", () -> {
            int active = rebuilding.incrementAndGet();
            rebuildPeak.accumulateAndGet(active, Math::max);
            metrics.counter("resolveflow.product_reviews.rebuild.loads", "outcome", "started")
                    .increment();
            LOG.debug("review_rebuild start id={} key={} at={}", trace, key, Instant.now());
            try {
                return reviews.publicPage(product, null, size);
            } catch (RuntimeException failure) {
                metrics.counter("resolveflow.product_reviews.rebuild.loads", "outcome", "failed")
                        .increment();
                throw failure;
            } finally {
                rebuilding.decrementAndGet();
                LOG.debug("review_rebuild end id={} key={} at={}", trace, key, Instant.now());
            }
        });
        // Both the read transaction and local DB permit are released before Redis I/O.
        try {
            if (owns.getAsBoolean()) {
                boolean stored = cache.publish(key, product, snapshot, result, Duration.ofSeconds(30));
                metrics.counter("resolveflow.product_reviews.cache.write", "outcome", stored ? "stored" : "invalidated")
                        .increment();
            } else
                metrics.counter("resolveflow.product_reviews.cache.write", "outcome", "lease_lost")
                        .increment();
        } catch (RuntimeException unavailable) {
            metrics.counter("resolveflow.product_reviews.cache.write", "outcome", "error")
                    .increment();
        }
        return result;
    }

    public Page read(String product, Long before, Integer limit) {
        int size = ProductReviewService.limit(before, limit);
        if (!enabled || before != null || size != 10)
            return database("page", () -> reviews.publicPage(product, before, size));
        String key = cache.reviewKey(product);
        try {
            var snapshot = snapshot(key, product);
            Page hit = cached(snapshot, product, "hit");
            if (hit != null) return hit;
            metrics.counter("resolveflow.product_reviews.cache", "outcome", "miss")
                    .increment();
            if (lock == null) return load(key, product, size, () -> true, snapshot);
            return lock.rebuild(
                    key,
                    owns -> {
                        var current = snapshot(key, product);
                        Page second = cached(current, product, "double_check_hit");
                        return second != null ? second : load(key, product, size, owns, current);
                    },
                    () -> {
                        Page second = cached(snapshot(key, product), product, "waiter_hit");
                        if (second != null) return second;
                        throw new ReadBusy();
                    },
                    () -> database("page", () -> reviews.publicPage(product, null, size)));
        } catch (CacheUnavailable unavailable) {
            return database("page", () -> reviews.publicPage(product, null, size));
        }
    }

    private static class CacheUnavailable extends RuntimeException {
        private static final long serialVersionUID = 1L;
    }

    public static class ReadBusy extends RuntimeException {
        private static final long serialVersionUID = 1L;
    }
}
