package com.resolveflow.shared.shopping;

import com.fasterxml.jackson.annotation.JsonProperty;
import java.time.Instant;
import java.util.List;

/** Public review projections never expose account, order line or request identifiers. */
public final class ProductReviewWire {
    private ProductReviewWire() {}

    public record Review(
            @JsonProperty("review_id") long reviewId,
            @JsonProperty("product_id") String productId,
            @JsonProperty("product_name") String productName,
            String variant,
            int rating,
            String body,
            String reply,
            long version,
            @JsonProperty("created_at") Instant createdAt,
            @JsonProperty("updated_at") Instant updatedAt) {}

    public record Summary(long count, Double average, List<Long> stars) {}

    public record Page(
            List<Review> items,
            Summary summary,
            @JsonProperty("next_before") Long nextBefore) {}

    public record Own(
            @JsonProperty("can_review") boolean canReview,
            @JsonProperty("blocked_reason") String blockedReason,
            Review review) {}

    public record Write(
            @tools.jackson.databind.annotation.JsonDeserialize(using = FulfillmentWire.StrictVersion.class)
            Long rating,

            @tools.jackson.databind.annotation.JsonDeserialize(using = StrictText.class)
            String body,

            @JsonProperty("expected_version")
            @tools.jackson.databind.annotation.JsonDeserialize(using = FulfillmentWire.StrictVersion.class)
            Long expectedVersion) {}

    public record Command(
            @JsonProperty("merchant_id") String merchantId,
            @JsonProperty("buyer_id") String buyerId,
            Write request) {}

    public record Reply(
            @tools.jackson.databind.annotation.JsonDeserialize(using = StrictText.class)
            String body,

            @JsonProperty("expected_version")
            @tools.jackson.databind.annotation.JsonDeserialize(using = FulfillmentWire.StrictVersion.class)
            Long expectedVersion) {}

    public record ReplyCommand(@JsonProperty("merchant_id") String merchantId, Reply request) {}

    public static class StrictText extends tools.jackson.databind.ValueDeserializer<String> {
        @Override
        public String deserialize(
                tools.jackson.core.JsonParser parser, tools.jackson.databind.DeserializationContext context) {
            if (parser.currentToken() != tools.jackson.core.JsonToken.VALUE_STRING)
                throw new IllegalArgumentException("body must be text");
            return parser.getString();
        }
    }
}
