package com.resolveflow.commerce.order;

import static org.assertj.core.api.Assertions.assertThat;

import com.resolveflow.commerce.CommerceDatabaseTest;
import java.util.Map;
import java.util.UUID;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.transaction.annotation.Transactional;
import tools.jackson.databind.ObjectMapper;

/** Read display art from the paid immutable snapshot, never today's catalog or another scope. */
@Transactional
class AftercareProductReadDatabaseTest extends CommerceDatabaseTest {
    @Autowired OrderLineReadService service;
    @Autowired JdbcTemplate jdbc;

    private String snapshot(String kind, String merchant, String customer) {
        String id = UUID.randomUUID().toString();
        jdbc.update("""
            INSERT INTO checkout_draft(draft_id,merchant_id,customer_id,idempotency_key,product_id,
                product_name,store_name,asset_key,sku_id,variant,quantity,unit_amount,total_amount,
                sku_version,status,created_at,expires_at,category,kind,line_count,cart_revision,
                multiline_request_hash,order_id,line_id,paid_at)
            VALUES(?,?,?,?, 'P-1001','历史商品','历史店铺','headphones','SKU-BLUE-L','蓝色',1,1999,1999,
                1,'PAID','2026-09-10 08:00:00','2026-09-10 09:00:00','electronics',?,?,?,?,
                '00000000-0000-4000-8000-0000000000aa','7002','2026-09-10 08:15:00')
            """, id, merchant, customer, id, kind, kind.equals("SINGLE") ? 1 : 2,
                kind.equals("SINGLE") ? null : 1L, kind.equals("SINGLE") ? null : "a".repeat(64));
        return id;
    }

    private Object art(String line) {
        var row = service.listByLine("M-1001", "C-2002", line).items().getFirst();
        return new ObjectMapper().convertValue(row, Map.class).get("assetKey");
    }

    @Test
    void singleSnapshotRemainsAfterCatalogArtChangesAndDoesNotDecorateOtherSkus() {
        snapshot("SINGLE", "M-1001", "C-2002");
        jdbc.update("UPDATE catalog_product SET asset_key='keyboard',name='已改名' WHERE product_id='P-1001'");
        assertThat(art("7002")).isEqualTo("headphones");
        assertThat(art("7001")).isNull();
        assertThat(service.readContext("7002").orElseThrow().linePaidAmount()).isEqualTo(1999);
        assertThat(service.listByLine("M-1002", "C-2002", "7002").items()).isEmpty();
    }

    @Test
    void multilineSnapshotSelectsTheExactSkuAndNeverUsesTheFlattenedFirstArt() {
        String id = snapshot("MULTI", "M-1001", "C-2002");
        jdbc.update("""
            INSERT INTO checkout_draft_line(draft_id,sku_id,product_id,product_name,variant,asset_key,
                category,quantity,unit_amount,line_amount,sku_version)
            VALUES(?,'SKU-BLUE-L','P-1002','历史键盘','蓝色','keyboard','electronics',1,1999,1999,1)
            """, id);
        assertThat(art("7002")).isEqualTo("keyboard");
        assertThat(art("7001")).isNull();
    }

    @Test
    void missingAndConflictingOwnershipSnapshotsHaveNoInventedArt() {
        assertThat(art("7002")).isNull();
        snapshot("SINGLE", "M-1002", "C-2004");
        assertThat(art("7002")).isNull();
    }
}
