package com.resolveflow.shared.shopping;

import com.fasterxml.jackson.annotation.JsonProperty;
import com.resolveflow.shared.shopping.ShoppingWire.DraftRequest;
import java.util.List;

public final class MultiCheckoutWire {
    private MultiCheckoutWire() {}

    public record QuoteRequest(
            @JsonProperty("expected_revision") Long expectedRevision,
            @JsonProperty("sku_ids") List<String> skuIds) {}

    public record Request(@JsonProperty("expected_revision") Long expectedRevision, List<DraftRequest> lines) {}

    public record Command(
            @JsonProperty("merchant_id") String merchantId,
            @JsonProperty("customer_id") String customerId,
            @JsonProperty("idempotency_key") String idempotencyKey,
            Request request) {}

    public record QuoteCommand(
            @JsonProperty("merchant_id") String merchantId,
            @JsonProperty("customer_id") String customerId,
            QuoteRequest request) {}

    public record Line(
            @JsonProperty("sku_id") String skuId,
            @JsonProperty("product_id") String productId,
            @JsonProperty("product_name") String productName,
            String variant,
            @JsonProperty("asset_key") String assetKey,
            String category,
            int quantity,
            @JsonProperty("unit_amount") long unitAmount,
            @JsonProperty("line_amount") long lineAmount,
            @JsonProperty("sku_version") long skuVersion) {}

    public record Quote(
            @JsonProperty("store_id") String storeId,
            @JsonProperty("store_name") String storeName,
            long revision,
            String currency,
            List<Line> lines,
            @JsonProperty("total_amount") long totalAmount) {}
}
