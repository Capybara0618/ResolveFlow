package com.resolveflow.commerce.catalog;

import com.resolveflow.shared.shopping.ShoppingWire.Product;
import io.micrometer.core.instrument.MeterRegistry;
import java.time.Duration;
import java.util.concurrent.Semaphore;
import java.util.concurrent.TimeUnit;
import java.util.function.Predicate;
import java.util.function.Supplier;
import org.redisson.api.RedissonClient;
import org.springframework.beans.factory.ObjectProvider;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Service;
import tools.jackson.databind.ObjectMapper;

/** Public display projections only. Checkout and tools continue to use database-backed domain services. */
@Service
public class PublicProductReadCache {
    private final ShoppingService shopping;
    private final PresentationService presentation;
    private final PublicCatalogCacheStore cache;
    private final ObjectMapper json;
    private final boolean enabled;
    private final ReviewRebuildLock lock;
    private final Semaphore databasePermits = new Semaphore(8, true);

    public PublicProductReadCache(
            ShoppingService shopping,
            PresentationService presentation,
            PublicCatalogCacheStore cache,
            ObjectMapper json,
            @Value("${resolveflow.catalog.cache-enabled:${resolveflow.product-reviews.cache-enabled:false}}")
                    boolean enabled,
            ObjectProvider<RedissonClient> clients,
            MeterRegistry metrics) {
        this.shopping = shopping;
        this.presentation = presentation;
        this.cache = cache;
        this.json = json;
        this.enabled = enabled;
        this.lock = clients.getIfAvailable() == null
                ? null
                : new ReviewRebuildLock(clients.getObject(), metrics, "resolveflow.catalog.rebuild");
    }

    public Product product(String id) {
        return read(id, cache.productKey(id), Product.class, p -> id.equals(p.productId()), () -> shopping.product(id));
    }

    public com.resolveflow.shared.shopping.PresentationWire.Product presentation(String id) {
        return read(
                id,
                cache.presentationKey(id),
                com.resolveflow.shared.shopping.PresentationWire.Product.class,
                p -> id.equals(p.product_id()),
                () -> presentation.product(id, null));
    }

    private <T> T read(String product, String key, Class<T> type, Predicate<T> valid, Supplier<T> source) {
        if (!enabled) return database(source);
        PublicCatalogCacheStore.Snapshot snapshot;
        T hit;
        try {
            snapshot = cache.read(key, product);
            hit = decode(snapshot, type, valid);
        } catch (RuntimeException unavailable) {
            return database(source);
        }
        if (hit != null) return hit;
        if (lock == null) return load(product, key, snapshot, source, () -> true);
        return lock.rebuild(
                key,
                owns -> {
                    PublicCatalogCacheStore.Snapshot second;
                    T cached;
                    try {
                        second = cache.read(key, product);
                        cached = decode(second, type, valid);
                    } catch (RuntimeException unavailable) {
                        return database(source);
                    }
                    return cached != null ? cached : load(product, key, second, source, owns);
                },
                () -> {
                    try {
                        T cached = decode(cache.read(key, product), type, valid);
                        if (cached != null) return cached;
                    } catch (RuntimeException unavailable) {
                        return database(source);
                    }
                    throw new ProductReviewReadCache.ReadBusy();
                },
                () -> database(source));
    }

    private <T> T decode(PublicCatalogCacheStore.Snapshot snapshot, Class<T> type, Predicate<T> valid) {
        if (snapshot.value() == null) return null;
        T result = json.readValue(snapshot.value(), type);
        if (result == null || !valid.test(result)) throw new IllegalStateException("invalid public product cache");
        return result;
    }

    private <T> T load(
            String product,
            String key,
            PublicCatalogCacheStore.Snapshot snapshot,
            Supplier<T> source,
            java.util.function.BooleanSupplier owns) {
        T result = database(source);
        try {
            if (owns.getAsBoolean()) cache.publish(key, product, snapshot, result, Duration.ofSeconds(60));
        } catch (RuntimeException unavailable) {
            // Return the database result even if Redis cannot accept the display cache.
        }
        return result;
    }

    private <T> T database(Supplier<T> source) {
        boolean acquired = false;
        try {
            acquired = databasePermits.tryAcquire(100, TimeUnit.MILLISECONDS);
            if (!acquired) throw new ProductReviewReadCache.ReadBusy();
            return source.get();
        } catch (InterruptedException interrupted) {
            Thread.currentThread().interrupt();
            throw new ProductReviewReadCache.ReadBusy();
        } finally {
            if (acquired) databasePermits.release();
        }
    }
}
