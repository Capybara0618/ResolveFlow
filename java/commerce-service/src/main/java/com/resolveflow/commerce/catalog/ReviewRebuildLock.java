package com.resolveflow.commerce.catalog;

import io.micrometer.core.instrument.MeterRegistry;
import java.util.concurrent.TimeUnit;
import java.util.function.BooleanSupplier;
import java.util.function.Function;
import java.util.function.Supplier;
import org.redisson.api.RLock;
import org.redisson.api.RedissonClient;

/** Coordinates presentation work only. Lease loss permits overlap and never authorizes a money write. */
final class ReviewRebuildLock {
    private final RedissonClient client;
    private final MeterRegistry metrics;
    private final String metric;

    ReviewRebuildLock(RedissonClient client, MeterRegistry metrics) {
        this(client, metrics, "resolveflow.product_reviews.rebuild");
    }

    ReviewRebuildLock(RedissonClient client, MeterRegistry metrics, String metric) {
        this.client = client;
        this.metrics = metrics;
        this.metric = metric;
    }

    private void count(String outcome) {
        metrics.counter(metric + ".lock", "outcome", outcome).increment();
    }

    <T> T rebuild(String key, Function<BooleanSupplier, T> owner, Supplier<T> waiter, Supplier<T> fallback) {
        RLock lock;
        boolean acquired;
        long started = System.nanoTime();
        try {
            lock = client.getLock(key + ":rebuild");
            acquired = lock.tryLock(100, 2000, TimeUnit.MILLISECONDS);
        } catch (InterruptedException interrupted) {
            Thread.currentThread().interrupt();
            count("interrupted");
            throw new ProductReviewReadCache.ReadBusy();
        } catch (RuntimeException unavailable) {
            count("unavailable");
            return fallback.get();
        } finally {
            metrics.timer(metric + ".wait").record(System.nanoTime() - started, TimeUnit.NANOSECONDS);
        }
        if (!acquired) {
            count("rejected");
            return waiter.get();
        }
        count("acquired");
        try {
            return owner.apply(lock::isHeldByCurrentThread);
        } finally {
            try {
                if (lock.isHeldByCurrentThread()) {
                    lock.unlock();
                    count("released");
                } else count("lease_lost");
            } catch (IllegalMonitorStateException expired) {
                count("lease_lost");
            } catch (RuntimeException unavailable) {
                count("unlock_unavailable");
            }
        }
    }
}
