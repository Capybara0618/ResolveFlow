package com.resolveflow.commerce.catalog;

import static org.assertj.core.api.Assertions.*;

import com.resolveflow.commerce.CommerceDatabaseTest;
import com.resolveflow.shared.shopping.ShoppingWire.*;
import java.sql.Timestamp;
import java.time.Instant;
import java.util.UUID;
import java.util.concurrent.Executors;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.jdbc.core.JdbcTemplate;

class ShoppingDatabaseTest extends CommerceDatabaseTest {
    @Autowired
    ShoppingService shop;

    @Autowired
    JdbcTemplate jdbc;

    private DraftCommand command(String key, int qty, long version) {
        return new DraftCommand("M-1001", "TEST-BUYER", key, new DraftRequest("SKU-1001-BLACK", qty, version));
    }

    @Test
    void directoryHasBothStoresSearchAndStablePagingWithoutPrivateFields() {
        assertThat(shop.stores()).extracting(Store::name).containsExactly("松间数码", "拾光家居");
        var a = shop.products(null, null, null, null, 2);
        var b = shop.products(null, null, null, a.nextAfter(), 2);
        assertThat(a.items()).extracting(Product::productId).containsExactly("P-1001", "P-1002");
        assertThat(b.items()).extracting(Product::productId).containsExactly("P-1003", "P-2001");
        assertThat(shop.products("%", null, null, null, null).items()).isEmpty();
        assertThat(shop.products("耳机", "electronics", "M-1002", null, null).items())
                .isEmpty();
        assertThat(shop.products(null, "home", null, null, null).items()).hasSize(3);
        assertThat(shop.product("P-1001").skus()).hasSize(2);
    }

    @Test
    void quoteUsesActualVariantAndBounds() {
        var q = shop.quote(new QuoteRequest("SKU-1001-SILVER", 3));
        assertThat(q.totalAmount()).isEqualTo(104700);
        assertThat(q.product().storeId()).isEqualTo("M-1001");
        for (int qty : new int[] {0, 11})
            assertThatThrownBy(() -> shop.quote(new QuoteRequest("SKU-1001-BLACK", qty)))
                    .isInstanceOf(IllegalArgumentException.class);
    }

    @Test
    void draftReplaysImmutableAmountAndRejectsChangedPayloadWithoutPublishingPaidRecords() {
        int orders = jdbc.queryForObject("SELECT COUNT(*) FROM orders", Integer.class);
        int ledgers = jdbc.queryForObject("SELECT COUNT(*) FROM payment_ledger", Integer.class);
        var c = command(UUID.randomUUID().toString(), 2, 1);
        var d = shop.create(c);
        assertThat(d.totalAmount()).isEqualTo(65800);
        assertThat(shop.create(c).draftId()).isEqualTo(d.draftId());
        assertThatThrownBy(() -> shop.create(command(c.idempotencyKey(), 3, 1)))
                .isInstanceOf(ShoppingService.Refused.class)
                .hasMessageContaining("另一份");
        assertThat(jdbc.queryForObject("SELECT COUNT(*) FROM orders", Integer.class))
                .isEqualTo(orders);
        assertThat(jdbc.queryForObject("SELECT COUNT(*) FROM payment_ledger", Integer.class))
                .isEqualTo(ledgers);
        assertThatThrownBy(() -> shop.read(d.draftId(), "M-1001", "OTHER")).isInstanceOf(ShoppingService.Refused.class);
        assertThatThrownBy(() -> shop.read(d.draftId(), "M-1002", "TEST-BUYER"))
                .isInstanceOf(ShoppingService.Refused.class);
    }

    @Test
    void priceChangesRejectNewRequestButDoNotRewriteExistingDraft() {
        var c = command(UUID.randomUUID().toString(), 1, 1);
        var d = shop.create(c);
        try {
            jdbc.update("UPDATE catalog_sku SET unit_amount=33900,version=2 WHERE sku_id='SKU-1001-BLACK'");
            assertThatThrownBy(() -> shop.create(command(UUID.randomUUID().toString(), 1, 1)))
                    .isInstanceOf(ShoppingService.Refused.class)
                    .hasMessageContaining("更新");
            assertThat(shop.create(c).totalAmount()).isEqualTo(32900);
            assertThat(shop.create(command(UUID.randomUUID().toString(), 1, 2)).totalAmount())
                    .isEqualTo(33900);
            assertThat(shop.read(d.draftId(), "M-1001", "TEST-BUYER").totalAmount())
                    .isEqualTo(32900);
        } finally {
            jdbc.update("UPDATE catalog_sku SET unit_amount=32900,version=1 WHERE sku_id='SKU-1001-BLACK'");
        }
    }

    @Test
    void delistedCatalogIsHiddenButOriginalCreateCanReplay() {
        var c = command(UUID.randomUUID().toString(), 1, 1);
        var d = shop.create(c);
        try {
            jdbc.update("UPDATE catalog_product SET listed=FALSE WHERE product_id='P-1001'");
            assertThatThrownBy(() -> shop.product("P-1001")).isInstanceOf(ShoppingService.Refused.class);
            assertThat(shop.products(null, null, null, null, null).items()).hasSize(5);
            assertThatThrownBy(() -> shop.create(command(UUID.randomUUID().toString(), 1, 1)))
                    .isInstanceOf(ShoppingService.Refused.class);
            assertThat(shop.create(c).draftId()).isEqualTo(d.draftId());
        } finally {
            jdbc.update("UPDATE catalog_product SET listed=TRUE WHERE product_id='P-1001'");
        }
    }

    @Test
    void expiryNeverCreatesNewDraftOrPaidOrder() {
        var c = command(UUID.randomUUID().toString(), 1, 1);
        var d = shop.create(c);
        jdbc.update(
                "UPDATE checkout_draft SET created_at=?,expires_at=? WHERE draft_id=?",
                Timestamp.from(Instant.now().minusSeconds(1800)),
                Timestamp.from(Instant.now().minusSeconds(900)),
                d.draftId());
        assertThat(shop.read(d.draftId(), "M-1001", "TEST-BUYER").status()).isEqualTo("EXPIRED");
        assertThat(shop.create(c).draftId()).isEqualTo(d.draftId());
        assertThat(shop.create(c).status()).isEqualTo("EXPIRED");
    }

    @Test
    void concurrentIdenticalRequestsPublishOneDraft() throws Exception {
        var c = command(UUID.randomUUID().toString(), 2, 1);
        try (var pool = Executors.newFixedThreadPool(2)) {
            var a = pool.submit(() -> shop.create(c));
            var b = pool.submit(() -> shop.create(c));
            assertThat(a.get().draftId()).isEqualTo(b.get().draftId());
        }
        assertThat(jdbc.queryForObject(
                        "SELECT COUNT(*) FROM checkout_draft WHERE idempotency_key=?",
                        Integer.class,
                        c.idempotencyKey()))
                .isEqualTo(1);
    }

    @Test
    void aSkuCannotBePurchasedWithAnotherStoreOwnership() {
        assertThatThrownBy(() -> shop.create(new DraftCommand(
                        "M-1002",
                        "TEST-BUYER",
                        UUID.randomUUID().toString(),
                        new DraftRequest("SKU-1001-BLACK", 1, 1L))))
                .isInstanceOf(ShoppingService.Refused.class);
    }
}
