package com.resolveflow.shared.shopping;

import com.fasterxml.jackson.annotation.JsonProperty;
import java.time.Instant;
import java.util.List;

/** Simulated checkout projections; ownership is accepted only in trusted service commands. */
public final class CheckoutWire {
    private CheckoutWire() {}

    public record EmptyRequest() {}

    public record Lookup(Payment payment) {}

    public record ScopeCommand(
            @JsonProperty("merchant_id") String merchantId,
            @JsonProperty("customer_id") String customerId) {}

    public record PayCommand(
            @JsonProperty("merchant_id") String merchantId,
            @JsonProperty("customer_id") String customerId,
            @JsonProperty("idempotency_key") String idempotencyKey) {}

    public record Payment(
            @JsonProperty("attempt_id") String attemptId,
            @JsonProperty("draft_id") String draftId,
            String status,
            @JsonProperty("total_amount") long totalAmount,
            String currency,
            @JsonProperty("created_at") Instant createdAt,
            @JsonProperty("finished_at") Instant finishedAt,
            @JsonProperty("order_id") String orderId,
            @JsonProperty("line_id") String lineId,
            @JsonProperty("paid_at") Instant paidAt) {}

    public record Line(
            @JsonProperty("line_id") String lineId,
            String sku,
            @JsonProperty("product_name") String productName,
            String variant,
            @JsonProperty("asset_key") String assetKey,
            int quantity,
            @JsonProperty("unit_amount") Long unitAmount,
            @JsonProperty("line_amount") long lineAmount) {}

    public record Purchase(
            @JsonProperty("purchase_id") String purchaseId,
            @JsonProperty("draft_id") String draftId,
            @JsonProperty("store_id") String storeId,
            @JsonProperty("store_name") String storeName,
            String status,
            @JsonProperty("total_amount") long totalAmount,
            String currency,
            @JsonProperty("created_at") Instant createdAt,
            @JsonProperty("expires_at") Instant expiresAt,
            @JsonProperty("paid_at") Instant paidAt,
            @JsonProperty("order_id") String orderId,
            List<Line> lines,
            Payment payment,

            @com.fasterxml.jackson.annotation.JsonInclude(com.fasterxml.jackson.annotation.JsonInclude.Include.NON_NULL)
            @JsonProperty("refund_status")
            String refundStatus,

            @com.fasterxml.jackson.annotation.JsonInclude(com.fasterxml.jackson.annotation.JsonInclude.Include.NON_NULL)
            @JsonProperty("shopping_stage")
            String shoppingStage) {
        public Purchase(
                String purchaseId,
                String draftId,
                String storeId,
                String storeName,
                String status,
                long totalAmount,
                String currency,
                Instant createdAt,
                Instant expiresAt,
                Instant paidAt,
                String orderId,
                List<Line> lines,
                Payment payment,
                String refundStatus) {
            this(
                    purchaseId,
                    draftId,
                    storeId,
                    storeName,
                    status,
                    totalAmount,
                    currency,
                    createdAt,
                    expiresAt,
                    paidAt,
                    orderId,
                    lines,
                    payment,
                    refundStatus,
                    null);
        }

        public Purchase(
                String purchaseId,
                String draftId,
                String storeId,
                String storeName,
                String status,
                long totalAmount,
                String currency,
                Instant createdAt,
                Instant expiresAt,
                Instant paidAt,
                String orderId,
                List<Line> lines,
                Payment payment) {
            this(
                    purchaseId,
                    draftId,
                    storeId,
                    storeName,
                    status,
                    totalAmount,
                    currency,
                    createdAt,
                    expiresAt,
                    paidAt,
                    orderId,
                    lines,
                    payment,
                    null);
        }
    }

    public record Purchases(
            List<Purchase> items,
            @JsonProperty("next_cursor") String nextCursor) {}
}
