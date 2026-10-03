package com.resolveflow.commerce.catalog;

import static org.assertj.core.api.Assertions.*;

import com.resolveflow.commerce.CommerceDatabaseTest;
import com.resolveflow.shared.security.JwtCodec;
import com.resolveflow.shared.shopping.ManagementWire.*;
import com.resolveflow.shared.shopping.ShoppingWire.DraftCommand;
import com.resolveflow.shared.shopping.ShoppingWire.DraftRequest;
import java.time.Instant;
import java.util.List;
import java.util.UUID;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.resttestclient.autoconfigure.AutoConfigureRestTestClient;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.test.web.servlet.client.RestTestClient;

@AutoConfigureRestTestClient
@SpringBootTest(webEnvironment = SpringBootTest.WebEnvironment.RANDOM_PORT)
class CatalogManagementTest extends CommerceDatabaseTest {
    @Autowired
    CatalogManagementService managed;

    @Autowired
    ShoppingService shop;

    @Autowired
    RestTestClient rest;

    @Autowired
    JwtCodec codec;

    private ProductWrite product(Long version, List<SkuWrite> skus) {
        return new ProductWrite("合成管理商品", "用于检验价格版本与归属", "outdoor", "backpack", true, version, skus);
    }

    @Test
    void priceChangeInvalidatesOldQuoteAndPreservesDraftSnapshot() {
        var p = managed.save(
                null,
                new ProductCommand(
                        "M-1001", "test", product(null, List.of(new SkuWrite(null, "蓝色", 9900L, 10, true)))));
        var sku = p.skus().getFirst();
        var draft = shop.create(new DraftCommand(
                "M-1001",
                "MANAGEMENT-TEST",
                UUID.randomUUID().toString(),
                new DraftRequest(sku.sku_id(), 1, sku.version())));
        var changed = managed.save(
                p.product_id(),
                new ProductCommand(
                        "M-1001",
                        "test",
                        product(p.version(), List.of(new SkuWrite(sku.sku_id(), "蓝色", 10900L, 10, true)))));
        assertThat(changed.skus().getFirst().version()).isEqualTo(2);
        assertThat(shop.read(draft.draftId(), "M-1001", "MANAGEMENT-TEST").totalAmount())
                .isEqualTo(9900);
        assertThatThrownBy(() -> shop.create(new DraftCommand(
                        "M-1001",
                        "MANAGEMENT-TEST",
                        UUID.randomUUID().toString(),
                        new DraftRequest(sku.sku_id(), 1, 1L))))
                .isInstanceOf(ShoppingService.Refused.class)
                .hasMessageContaining("重新确认");
        assertThatThrownBy(() -> managed.save(
                        p.product_id(),
                        new ProductCommand(
                                "M-1001",
                                "test",
                                product(1L, List.of(new SkuWrite(sku.sku_id(), "蓝色", 1L, 10, true))))))
                .isInstanceOf(ShoppingService.Refused.class);
        assertThatThrownBy(() -> managed.read("M-1002", p.product_id())).isInstanceOf(ShoppingService.Refused.class);
        assertThatThrownBy(() -> managed.save(
                        p.product_id(),
                        new ProductCommand(
                                "M-1002",
                                "test",
                                product(2L, List.of(new SkuWrite(sku.sku_id(), "蓝色", 1L, 10, true))))))
                .isInstanceOf(ShoppingService.Refused.class);
    }

    @Test
    void cannotDeleteOrImportSkuAndDelistingMakesProductUnbuyable() {
        var p = managed.save(
                null,
                new ProductCommand(
                        "M-1001", "test", product(null, List.of(new SkuWrite(null, "蓝色", 9900L, 10, true)))));
        assertThatThrownBy(() -> managed.save(
                        p.product_id(),
                        new ProductCommand(
                                "M-1001",
                                "test",
                                product(1L, List.of(new SkuWrite("SKU-1001-BLACK", "蓝色", 9900L, 10, true))))))
                .isInstanceOf(ShoppingService.Refused.class);
        var s = p.skus().getFirst();
        managed.save(
                p.product_id(),
                new ProductCommand(
                        "M-1001",
                        "test",
                        new ProductWrite(
                                p.name(),
                                p.description(),
                                p.category(),
                                p.asset_key(),
                                false,
                                1L,
                                List.of(new SkuWrite(s.sku_id(), s.variant(), s.unit_amount(), 10, false)))));
        assertThat(managed.read("M-1001", p.product_id()).listed()).isFalse();
        assertThatThrownBy(() -> shop.product(p.product_id())).isInstanceOf(ShoppingService.Refused.class);
    }

    @Test
    void storeSyncIsIdempotentAndRejectsStaleOrChangedSameRevision() {
        String id = "SYNC-" + UUID.randomUUID();
        var s = new StoreSync(id, "同步商家", "合成同步商家", true, 1);
        assertThat(managed.sync(s)).isEqualTo(s);
        assertThat(managed.sync(s)).isEqualTo(s);
        assertThatThrownBy(() -> managed.sync(new StoreSync(id, "不同内容", s.description(), true, 1)))
                .isInstanceOf(ShoppingService.Refused.class);
        managed.sync(new StoreSync(id, s.name(), s.description(), false, 2));
        assertThatThrownBy(() -> managed.sync(s)).isInstanceOf(ShoppingService.Refused.class);
    }

    @Test
    void agentCannotReadOrWriteCatalogManagementEvenWithForgedScope() {
        for (var pair : new String[][] {
            {"agent-service", "commerce:read"},
            {"agent-service", "commerce:catalog"},
            {"case-service", "commerce:checkout"}
        }) {
            String auth = "Bearer " + codec.issueServiceToken(pair[0], null, null, pair[1], Instant.now());
            rest.get()
                    .uri("/internal/v1/catalog-management/products?merchant_id=M-1001")
                    .header("Authorization", auth)
                    .exchange()
                    .expectStatus()
                    .isForbidden();
            rest.post()
                    .uri("/internal/v1/catalog-management/stores")
                    .header("Authorization", auth)
                    .body(new StoreSync("X", "X", "X", true, 1))
                    .exchange()
                    .expectStatus()
                    .isForbidden();
        }
    }
}
