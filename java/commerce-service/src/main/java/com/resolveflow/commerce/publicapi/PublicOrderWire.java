package com.resolveflow.commerce.publicapi;

import java.time.Instant;
import java.util.List;

/** Public order projections retain optional historical fields and trusted buyer store labels. */
public final class PublicOrderWire {
    private PublicOrderWire() {}

    public record Page(List<Summary> items, Meta page) {}

    @com.fasterxml.jackson.annotation.JsonInclude(com.fasterxml.jackson.annotation.JsonInclude.Include.NON_NULL)
    public record Meta(
            @com.fasterxml.jackson.annotation.JsonProperty("next_cursor")
            String nextCursor,

            int limit) {}

    public record Summary(
            @com.fasterxml.jackson.annotation.JsonProperty("order_id")
            String orderId,

            @com.fasterxml.jackson.annotation.JsonProperty("line_id")
            String lineId,

            String sku,

            // Optional presentation members (core OpenAPI Summary). Nullable rather than
            // defaulted: a historical line has no product name, and a client that filled one in
            // would be inventing a product. Unknown members are still refused by this service's
            // Jackson configuration, so Commerce cannot add a third one silently.
            //
            // NON_NULL on these two **only**: an absent display field is omitted, the way
            // `next_cursor` is, so the public order view answers exactly as it did before V7. A
            // service-wide NON_NULL would also hide a null in a required member, which is a
            // protocol violation this service should pass on loudly rather than swallow.
            @com.fasterxml.jackson.annotation.JsonProperty("product_name")
            @com.fasterxml.jackson.annotation.JsonInclude(com.fasterxml.jackson.annotation.JsonInclude.Include.NON_NULL)
            String productName,

            @com.fasterxml.jackson.annotation.JsonProperty("variant_text")
            @com.fasterxml.jackson.annotation.JsonInclude(com.fasterxml.jackson.annotation.JsonInclude.Include.NON_NULL)
            String variantText,

            String category,
            int quantity,

            @com.fasterxml.jackson.annotation.JsonProperty("line_paid_amount")
            long linePaidAmount,

            String currency,

            @com.fasterxml.jackson.annotation.JsonProperty("paid_at")
            Instant paidAt,

            String status,
            long version,

            @com.fasterxml.jackson.annotation.JsonProperty("merchant_id")
            @com.fasterxml.jackson.annotation.JsonInclude(com.fasterxml.jackson.annotation.JsonInclude.Include.NON_NULL)
            String merchantId,

            @com.fasterxml.jackson.annotation.JsonProperty("merchant_name")
            @com.fasterxml.jackson.annotation.JsonInclude(com.fasterxml.jackson.annotation.JsonInclude.Include.NON_NULL)
            String merchantName,

            @com.fasterxml.jackson.annotation.JsonProperty("asset_key")
            @com.fasterxml.jackson.annotation.JsonInclude(com.fasterxml.jackson.annotation.JsonInclude.Include.NON_NULL)
            String assetKey) {
        public static Summary from(com.resolveflow.commerce.order.OrderLineRow row) {
            return new Summary(
                    row.orderId(),
                    row.lineId(),
                    row.sku(),
                    row.productName(),
                    row.variantText(),
                    row.category(),
                    row.quantity(),
                    row.linePaidAmount(),
                    row.currency(),
                    row.paidAt(),
                    row.status(),
                    row.version(),
                    null,
                    null,
                    row.assetKey());
        }

        public Summary(
                String orderId,
                String lineId,
                String sku,
                String productName,
                String variantText,
                String category,
                int quantity,
                long linePaidAmount,
                String currency,
                Instant paidAt,
                String status,
                long version) {
            this(
                    orderId,
                    lineId,
                    sku,
                    productName,
                    variantText,
                    category,
                    quantity,
                    linePaidAmount,
                    currency,
                    paidAt,
                    status,
                    version,
                    null,
                    null,
                    null);
        }

        public Summary withMerchant(String merchantId, String merchantName) {
            return new Summary(
                    orderId,
                    lineId,
                    sku,
                    productName,
                    variantText,
                    category,
                    quantity,
                    linePaidAmount,
                    currency,
                    paidAt,
                    status,
                    version,
                    merchantId,
                    merchantName,
                    assetKey);
        }
    }
}
