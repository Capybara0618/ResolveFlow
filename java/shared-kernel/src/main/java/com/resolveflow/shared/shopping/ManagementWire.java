package com.resolveflow.shared.shopping;

import com.fasterxml.jackson.annotation.JsonProperty;
import java.util.List;

/** Minimal platform/store catalog administration; no payment or aftersale authority. */
public final class ManagementWire {
    private ManagementWire() {}

    public record StoreSync(
            @JsonProperty("store_id") String storeId, String name, String description, boolean enabled, long version) {}

    public record SkuWrite(
            @JsonProperty("sku_id") String skuId,
            String variant,
            @JsonProperty("unit_amount") Long unitAmount,
            @JsonProperty("max_quantity") Integer maxQuantity,
            Boolean listed) {}

    public record ProductWrite(
            String name,
            String description,
            String category,
            @JsonProperty("asset_key") String assetKey,
            Boolean listed,
            @JsonProperty("expected_version") Long expectedVersion,
            List<SkuWrite> skus) {}

    public record ProductCommand(
            @JsonProperty("merchant_id") String merchantId, String actor, ProductWrite product) {}

    public record Sku(
            String sku_id, String variant, long unit_amount, int max_quantity, boolean listed, long version) {}

    public record Product(
            String product_id,
            String store_id,
            String name,
            String description,
            String category,
            String asset_key,
            boolean listed,
            long version,
            List<Sku> skus) {}

    public record Products(List<Product> items, String next_after) {}
}
