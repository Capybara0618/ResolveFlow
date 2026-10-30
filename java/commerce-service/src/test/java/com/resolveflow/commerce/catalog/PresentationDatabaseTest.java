package com.resolveflow.commerce.catalog;

import static org.assertj.core.api.Assertions.*;

import com.resolveflow.commerce.CommerceDatabaseTest;
import com.resolveflow.shared.shopping.PresentationWire.*;
import java.util.*;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.jdbc.core.JdbcTemplate;

class PresentationDatabaseTest extends CommerceDatabaseTest {
    @Autowired
    PresentationService service;

    @Autowired
    JdbcTemplate db;

    @Autowired
    ShoppingService shop;

    @Test
    void variantMappingSurvivesReorderingAndRejectsOtherProductVariantsOrPhotos() {
        String a = UUID.randomUUID().toString(), b = UUID.randomUUID().toString();
        var old = service.product("P-1001", "M-1001");
        var value = service.saveProduct(
                "P-1001",
                new ProductCommand(
                        "M-1001",
                        "admin",
                        new ProductWrite(old.version(), List.of(b, a), List.of(), "", "", Map.of("黑色", a, "银色", b))));
        assertThat(service.product("P-1001", null).variant_images())
                .containsEntry("黑色", a)
                .containsEntry("银色", b);
        assertThatThrownBy(() -> service.saveProduct(
                        "P-1001",
                        new ProductCommand(
                                "M-1001",
                                "admin",
                                new ProductWrite(
                                        value.version(), List.of(a, b), List.of(), "", "", Map.of("无此款式", a)))))
                .isInstanceOf(IllegalArgumentException.class);
        assertThatThrownBy(() -> service.saveProduct(
                        "P-1001",
                        new ProductCommand(
                                "M-1001",
                                "admin",
                                new ProductWrite(value.version(), List.of(a), List.of(), "", "", Map.of("黑色", b)))))
                .isInstanceOf(IllegalArgumentException.class);
        var next = service.saveProduct(
                "P-1001",
                new ProductCommand(
                        "M-1001", "admin", new ProductWrite(value.version(), List.of(a), List.of(), "", "")));
        assertThat(next.variant_images()).containsExactlyEntriesOf(Map.of("黑色", a));
    }

    @Test
    void orderedImagesAndNotesPersistWithOwnershipVersionAndPublicationChecks() {
        String a = UUID.randomUUID().toString(), b = UUID.randomUUID().toString();
        var before = service.product("P-1001", "M-1001");
        var request = new ProductWrite(
                before.version(), List.of(a, b), List.of(new Spec("材质", "合成测试材质")), "配送说明\n第二行", "售后说明");
        var value = service.saveProduct("P-1001", new ProductCommand("M-1001", "demo-admin", request));
        assertThat(service.product("P-1001", null)).isEqualTo(value);
        assertThat(value.images()).containsExactly(a, b);
        assertThat(shop.product("P-1001").coverImageId()).isEqualTo(a);
        assertThat(shop.products(null, null, "M-1001", null, 24).items())
                .filteredOn(p -> p.productId().equals("P-1001"))
                .extracting(com.resolveflow.shared.shopping.ShoppingWire.Product::coverImageId)
                .containsExactly(a);
        assertThat(shop.quote(new com.resolveflow.shared.shopping.ShoppingWire.QuoteRequest("SKU-1001-BLACK", 1))
                        .totalAmount())
                .isEqualTo(32900);
        assertThat(service.published(a).published()).isTrue();
        assertThatThrownBy(() -> service.saveProduct("P-1001", new ProductCommand("M-1001", "demo-admin", request)))
                .isInstanceOf(ShoppingService.Refused.class);
        assertThatThrownBy(() -> service.saveProduct("P-1001", new ProductCommand("M-1002", "other-admin", request)))
                .isInstanceOf(ShoppingService.Refused.class);
        db.update("UPDATE catalog_product SET listed=FALSE WHERE product_id='P-1001'");
        try {
            assertThat(service.published(a).published()).isFalse();
            assertThatThrownBy(() -> service.product("P-1001", null)).isInstanceOf(ShoppingService.Refused.class);
        } finally {
            db.update("UPDATE catalog_product SET listed=TRUE WHERE product_id='P-1001'");
        }
    }

    @Test
    void storeProfileVersionAndLogoPublishFollowStoreVisibility() {
        String image = UUID.randomUUID().toString();
        var old = service.store("M-1001", false);
        var next = service.saveStore(new StoreCommand(
                "M-1001", "demo-admin", new StoreWrite(old.version(), "测试店铺简介", image, "13000000000", "9:00–18:00")));
        assertThat(service.store("M-1001", true)).isEqualTo(next);
        assertThat(service.published(image).published()).isTrue();
        db.update("UPDATE catalog_store SET enabled=FALSE WHERE store_id='M-1001'");
        try {
            assertThat(service.published(image).published()).isFalse();
            assertThatThrownBy(() -> service.store("M-1001", true)).isInstanceOf(ShoppingService.Refused.class);
        } finally {
            db.update("UPDATE catalog_store SET enabled=TRUE WHERE store_id='M-1001'");
        }
    }
}
