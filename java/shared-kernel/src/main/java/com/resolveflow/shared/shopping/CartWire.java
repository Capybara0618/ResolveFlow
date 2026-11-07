package com.resolveflow.shared.shopping;

import com.fasterxml.jackson.annotation.JsonProperty;
import java.util.List;

/** A cart write sets an absolute quantity. Zero removes an item, including unavailable items. */
public final class CartWire {
    private CartWire() {}

    public record Request(
            @JsonProperty("sku_id") String skuId,
            Integer quantity,
            @JsonProperty("expected_revision") Long expectedRevision,
            @JsonProperty("expected_sku_version") Long expectedSkuVersion) {}

    public record Command(
            @JsonProperty("merchant_id") String merchantId,
            @JsonProperty("buyer_id") String buyerId,
            @JsonProperty("idempotency_key") String idempotencyKey,
            Request request) {}

    public record Receipt(@JsonProperty("store_id") String storeId, long revision) {}

    public record Item(
            @JsonProperty("sku_id") String skuId,
            @JsonProperty("product_id") String productId,
            @JsonProperty("product_name") String productName,
            String variant,
            @JsonProperty("asset_key") String assetKey,
            int quantity,
            @JsonProperty("unit_amount") long unitAmount,
            @JsonProperty("total_amount") long totalAmount,
            @JsonProperty("max_quantity") int maxQuantity,
            @JsonProperty("sku_version") long skuVersion,
            @JsonProperty("price_changed") boolean priceChanged,
            String availability) {}

    public record Group(
            @JsonProperty("store_id") String storeId,
            @JsonProperty("store_name") String storeName,
            long revision,
            String currency,
            List<Item> items) {}

    public record Cart(List<Group> stores) {}
}
