package com.resolveflow.commerce.catalog;

import static org.assertj.core.api.Assertions.*;

import com.resolveflow.commerce.CommerceDatabaseTest;
import com.resolveflow.shared.shopping.CartWire.*;
import java.util.UUID;
import java.util.concurrent.Executors;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.jdbc.core.JdbcTemplate;

class CartDatabaseTest extends CommerceDatabaseTest {
    @Autowired
    CartService cart;

    @Autowired
    JdbcTemplate jdbc;

    private String owner() {
        return "CART-" + UUID.randomUUID();
    }

    private Command command(String store, String owner, String sku, int qty, long revision, Long version) {
        return new Command(store, owner, UUID.randomUUID().toString(), new Request(sku, qty, revision, version));
    }

    @Test
    void absoluteQuantitiesReplayAndBuyerAndStoreStaySeparate() {
        var buyer = owner();
        var c = command("M-1001", buyer, "SKU-1001-BLACK", 2, 0, 1L);
        assertThat(cart.write(c).revision()).isEqualTo(1);
        assertThat(cart.write(c).revision()).isEqualTo(1);
        cart.write(command("M-1002", buyer, "SKU-2001-CREAM", 1, 0, 1L));
        var a = cart.read("M-1001", buyer);
        var b = cart.read("M-1002", buyer);
        assertThat(a.items().getFirst().quantity()).isEqualTo(2);
        assertThat(a.items().getFirst().totalAmount()).isEqualTo(65800);
        assertThat(b.items().getFirst().skuId()).isEqualTo("SKU-2001-CREAM");
        assertThat(cart.read("M-1001", owner()).items()).isEmpty();
        cart.write(command("M-1001", buyer, "SKU-1001-BLACK", 3, 1, 1L));
        assertThat(cart.write(c).revision()).isEqualTo(1);
        assertThat(cart.read("M-1001", buyer).items().getFirst().quantity()).isEqualTo(3);
        assertThatThrownBy(() -> cart.write(new Command(
                        c.merchantId(),
                        c.customerId(),
                        c.idempotencyKey(),
                        new Request(c.request().skuId(), 4, 2L, 1L))))
                .isInstanceOf(ShoppingService.Refused.class)
                .hasMessageContaining("另一项");
    }

    @Test
    void staleRevisionAndWrongStoreCannotMutateCart() {
        var buyer = owner();
        cart.write(command("M-1001", buyer, "SKU-1001-BLACK", 1, 0, 1L));
        assertThatThrownBy(() -> cart.write(command("M-1001", buyer, "SKU-1002-WHITE", 2, 0, 1L)))
                .isInstanceOf(ShoppingService.Refused.class)
                .hasMessageContaining("购物车已更新");
        assertThatThrownBy(() -> cart.write(command("M-1002", buyer, "SKU-1001-BLACK", 1, 0, 1L)))
                .isInstanceOf(ShoppingService.Refused.class);
        assertThat(cart.read("M-1002", buyer).revision()).isZero();
        assertThat(cart.read("M-1001", buyer).revision()).isEqualTo(1);
    }

    @Test
    void unavailableItemsRemainVisibleAndRemovableAndEmptyCartDoesNotResetRevision() {
        var buyer = owner();
        cart.write(command("M-1001", buyer, "SKU-1001-BLACK", 2, 0, 1L));
        try {
            jdbc.update(
                    "UPDATE catalog_sku SET unit_amount=33900,version=2,max_quantity=1 WHERE sku_id='SKU-1001-BLACK'");
            var item = cart.read("M-1001", buyer).items().getFirst();
            assertThat(item.priceChanged()).isTrue();
            assertThat(item.unitAmount()).isEqualTo(33900);
            assertThat(item.availability()).isEqualTo("QUANTITY_EXCEEDED");
            assertThatThrownBy(() -> cart.write(command("M-1001", buyer, "SKU-1001-BLACK", 1, 1, 1L)))
                    .isInstanceOf(ShoppingService.Refused.class)
                    .hasMessageContaining("商品已更新");
            jdbc.update("UPDATE catalog_product SET listed=FALSE WHERE product_id='P-1001'");
            assertThat(cart.read("M-1001", buyer).items().getFirst().availability())
                    .isEqualTo("DELISTED");
            jdbc.update("UPDATE catalog_store SET enabled=FALSE WHERE store_id='M-1001'");
            assertThat(cart.read("M-1001", buyer).items().getFirst().availability())
                    .isEqualTo("STORE_DISABLED");
            cart.write(command("M-1001", buyer, "SKU-1001-BLACK", 0, 1, null));
            assertThat(cart.read("M-1001", buyer).items()).isEmpty();
            assertThat(cart.read("M-1001", buyer).revision()).isEqualTo(2);
        } finally {
            jdbc.update("UPDATE catalog_store SET enabled=TRUE WHERE store_id='M-1001'");
            jdbc.update("UPDATE catalog_product SET listed=TRUE WHERE product_id='P-1001'");
            jdbc.update(
                    "UPDATE catalog_sku SET unit_amount=32900,version=1,max_quantity=10 WHERE sku_id='SKU-1001-BLACK'");
        }
        assertThatThrownBy(() -> cart.write(command("M-1001", buyer, "SKU-1001-BLACK", 1, 0, 1L)))
                .isInstanceOf(ShoppingService.Refused.class);
    }

    @Test
    void concurrentIdenticalWritesDoNotDuplicateAndCompetingWritesHaveOneWinner() throws Exception {
        var buyer = owner();
        var c = command("M-1001", buyer, "SKU-1001-BLACK", 1, 0, 1L);
        try (var pool = Executors.newFixedThreadPool(2)) {
            var a = pool.submit(() -> cart.write(c));
            var b = pool.submit(() -> cart.write(c));
            assertThat(a.get()).isEqualTo(b.get());
            var x = pool.submit(() -> outcome(command("M-1001", buyer, "SKU-1001-BLACK", 2, 1, 1L)));
            var y = pool.submit(() -> outcome(command("M-1001", buyer, "SKU-1001-BLACK", 3, 1, 1L)));
            assertThat(java.util.List.of(x.get(), y.get())).containsExactlyInAnyOrder("ok", "CART_CHANGED");
        }
        assertThat(cart.read("M-1001", buyer).revision()).isEqualTo(2);
    }

    private String outcome(Command c) {
        try {
            cart.write(c);
            return "ok";
        } catch (ShoppingService.Refused e) {
            return e.code;
        }
    }

    @Test
    void twentySkuLimitIsAtomicWhileUpdatingAnExistingItemRemainsPossible() {
        var buyer = owner();
        try {
            for (int i = 0; i < 21; i++)
                jdbc.update(
                        "INSERT INTO catalog_sku(sku_id,product_id,variant,unit_amount,max_quantity) VALUES(?,'P-1003','测试规格',100,10)",
                        "CART-LIMIT-" + i);
            for (int i = 0; i < 20; i++) cart.write(command("M-1001", buyer, "CART-LIMIT-" + i, 1, i, 1L));
            assertThatThrownBy(() -> cart.write(command("M-1001", buyer, "CART-LIMIT-20", 1, 20, 1L)))
                    .isInstanceOf(ShoppingService.Refused.class)
                    .hasMessageContaining("最多");
            assertThat(cart.read("M-1001", buyer).revision()).isEqualTo(20);
            cart.write(command("M-1001", buyer, "CART-LIMIT-0", 2, 20, 1L));
            assertThat(cart.read("M-1001", buyer).items()).hasSize(20);
        } finally {
            jdbc.update("DELETE FROM shopping_cart_item WHERE customer_id=?", buyer);
            jdbc.update("DELETE FROM catalog_sku WHERE sku_id LIKE 'CART-LIMIT-%'");
        }
    }

    @Test
    void malformedInputsNeverCreatePaymentOrDrafts() {
        var buyer = owner();
        int drafts = jdbc.queryForObject("SELECT COUNT(*) FROM checkout_draft", Integer.class);
        for (int qty : new int[] {-1, 11, 101})
            assertThatThrownBy(() -> cart.write(command("M-1001", buyer, "SKU-1001-BLACK", qty, 0, 1L)))
                    .isInstanceOf(IllegalArgumentException.class);
        assertThat(cart.read("M-1001", buyer).revision()).isZero();
        assertThat(jdbc.queryForObject("SELECT COUNT(*) FROM checkout_draft", Integer.class))
                .isEqualTo(drafts);
    }
}
