package com.resolveflow.shared.shopping;

import com.fasterxml.jackson.annotation.JsonProperty;
import java.time.Instant;
import java.util.List;

/** Public projections and trusted service commands; persistence stays in Commerce. */
public final class ShoppingWire {
    private ShoppingWire() {}

    public record Store(@JsonProperty("store_id") String storeId, String name, String description) {}

    public record Sku(
            @JsonProperty("sku_id") String skuId,
            String variant,
            @JsonProperty("unit_amount") long unitAmount,
            @JsonProperty("max_quantity") int maxQuantity,
            long version) {}

    public record Product(
            @JsonProperty("product_id") String productId,
            @JsonProperty("store_id") String storeId,
            @JsonProperty("store_name") String storeName,
            String name,
            String description,
            String category,
            @JsonProperty("asset_key") String assetKey,
            @JsonProperty("from_amount") long fromAmount,
            String currency,
            List<Sku> skus,

            @com.fasterxml.jackson.annotation.JsonInclude(com.fasterxml.jackson.annotation.JsonInclude.Include.NON_NULL)
            @JsonProperty("cover_image_id")
            String coverImageId) {
        public Product(
                String productId,
                String storeId,
                String storeName,
                String name,
                String description,
                String category,
                String assetKey,
                long fromAmount,
                String currency,
                List<Sku> skus) {
            this(
                    productId,
                    storeId,
                    storeName,
                    name,
                    description,
                    category,
                    assetKey,
                    fromAmount,
                    currency,
                    skus,
                    null);
        }
    }

    public record Products(
            List<Product> items, @JsonProperty("next_after") String nextAfter) {}

    public record QuoteRequest(@JsonProperty("sku_id") String skuId, Integer quantity) {}

    public record DraftRequest(
            @JsonProperty("sku_id") String skuId,
            Integer quantity,
            @JsonProperty("expected_sku_version") Long expectedSkuVersion,

            @com.fasterxml.jackson.annotation.JsonInclude(com.fasterxml.jackson.annotation.JsonInclude.Include.NON_NULL)
            ShippingWire.Selection shipping) {
        public DraftRequest(String skuId, Integer quantity, Long expectedSkuVersion) {
            this(skuId, quantity, expectedSkuVersion, null);
        }
    }

    public record Quote(
            Product product,
            Sku sku,
            int quantity,
            @JsonProperty("total_amount") long totalAmount,
            String currency) {}

    public record Draft(
            @JsonProperty("draft_id") String draftId,
            @JsonProperty("store_id") String storeId,
            @JsonProperty("store_name") String storeName,
            @JsonProperty("product_id") String productId,
            @JsonProperty("product_name") String productName,
            @JsonProperty("asset_key") String assetKey,
            @JsonProperty("sku_id") String skuId,
            String variant,
            int quantity,
            @JsonProperty("unit_amount") long unitAmount,
            @JsonProperty("total_amount") long totalAmount,
            String currency,
            String status,
            @JsonProperty("created_at") Instant createdAt,
            @JsonProperty("expires_at") Instant expiresAt) {}

    public record DraftCommand(
            @JsonProperty("merchant_id") String merchantId,
            @JsonProperty("customer_id") String customerId,
            @JsonProperty("idempotency_key") String idempotencyKey,
            DraftRequest request,

            @com.fasterxml.jackson.annotation.JsonInclude(com.fasterxml.jackson.annotation.JsonInclude.Include.NON_NULL)
            @JsonProperty("shipping_snapshot")
            ShippingWire.Snapshot shippingSnapshot) {
        public DraftCommand(String merchantId, String customerId, String idempotencyKey, DraftRequest request) {
            this(merchantId, customerId, idempotencyKey, request, null);
        }
    }
}
