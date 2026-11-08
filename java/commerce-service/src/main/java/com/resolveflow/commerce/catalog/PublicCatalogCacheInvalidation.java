package com.resolveflow.commerce.catalog;

import java.util.UUID;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Component;
import org.springframework.transaction.PlatformTransactionManager;
import org.springframework.transaction.TransactionDefinition;
import org.springframework.transaction.support.TransactionSynchronization;
import org.springframework.transaction.support.TransactionSynchronizationManager;
import org.springframework.transaction.support.TransactionTemplate;

/** Persist in the writer's transaction, then deliver outside it. Conditional deletion retains newer work. */
@Component
public class PublicCatalogCacheInvalidation {
    private static final Logger LOG = LoggerFactory.getLogger(PublicCatalogCacheInvalidation.class);
    private final JdbcTemplate jdbc;
    private final PublicCatalogCacheStore cache;
    private final TransactionTemplate cleanup;
    private final boolean enabled;

    public PublicCatalogCacheInvalidation(
            JdbcTemplate jdbc,
            PublicCatalogCacheStore cache,
            PlatformTransactionManager transactions,
            @Value("${resolveflow.catalog.cache-enabled:${resolveflow.product-reviews.cache-enabled:false}}")
                    boolean catalogEnabled,
            @Value("${resolveflow.product-reviews.cache-enabled:false}") boolean reviewsEnabled) {
        this.jdbc = jdbc;
        this.cache = cache;
        this.enabled = catalogEnabled || reviewsEnabled;
        this.cleanup = new TransactionTemplate(transactions);
        cleanup.setPropagationBehavior(TransactionDefinition.PROPAGATION_REQUIRES_NEW);
    }

    public void productChanged(String product) {
        changed(product, 3);
    }

    public void presentationChanged(String product) {
        changed(product, 1);
    }

    public void reviewsChanged(String product) {
        changed(product, 2);
    }

    private void changed(String product, int targets) {
        if (!enabled) return;
        if (!TransactionSynchronizationManager.isActualTransactionActive())
            throw new IllegalStateException("cache invalidation requires the business transaction");
        String token = UUID.randomUUID().toString();
        jdbc.update("""
                INSERT INTO public_catalog_cache_invalidation(cache_namespace,product_id,token,targets)
                VALUES(?,?,?,?) ON DUPLICATE KEY UPDATE token=VALUES(token),targets=targets | VALUES(targets),updated_at=CURRENT_TIMESTAMP(6)
                """, cache.namespace(), product, token, targets);
        int pendingTargets = jdbc.queryForObject(
                "SELECT targets FROM public_catalog_cache_invalidation WHERE cache_namespace=? AND product_id=?",
                Integer.class,
                cache.namespace(),
                product);
        TransactionSynchronizationManager.registerSynchronization(new TransactionSynchronization() {
            @Override
            public void afterCommit() {
                // Do no more SQL while Spring is still releasing the writer's connection.
                // The scheduler confirms invalidation and removes this durable pending record.
                try {
                    cache.invalidate(product, pendingTargets);
                } catch (RuntimeException failure) {
                    deferred(product, failure);
                }
            }
        });
    }

    public void storeChanged(String store) {
        if (!enabled) return;
        for (String product : jdbc.queryForList(
                "SELECT product_id FROM catalog_product WHERE store_id=? ORDER BY product_id", String.class, store))
            productChanged(product);
    }

    private void deliver(String product, String token) {
        try {
            var targets = cleanup.execute(status -> jdbc.queryForList(
                    "SELECT targets FROM public_catalog_cache_invalidation WHERE cache_namespace=? AND product_id=? AND token=?",
                    Integer.class,
                    cache.namespace(),
                    product,
                    token));
            if (targets == null || targets.isEmpty()) return;
            cache.invalidate(product, targets.getFirst());
            cleanup.executeWithoutResult(status -> jdbc.update(
                    "DELETE FROM public_catalog_cache_invalidation WHERE cache_namespace=? AND product_id=? AND token=?",
                    cache.namespace(),
                    product,
                    token));
        } catch (RuntimeException failure) {
            deferred(product, failure);
        }
    }

    private static void deferred(String product, RuntimeException failure) {
        LOG.warn(
                "Public catalog cache invalidation deferred for product {} ({})",
                product,
                failure.getClass().getSimpleName());
    }

    @Scheduled(
            fixedDelayString = "${resolveflow.catalog.invalidation-poll-ms:2000}",
            initialDelayString = "${resolveflow.catalog.invalidation-poll-ms:2000}")
    public void retryPending() {
        if (!enabled) return;
        for (var row : jdbc.queryForList("""
                SELECT product_id,token FROM public_catalog_cache_invalidation WHERE cache_namespace=?
                ORDER BY updated_at,product_id LIMIT 20
                """, cache.namespace()))
            deliver((String) row.get("product_id"), (String) row.get("token"));
    }
}
