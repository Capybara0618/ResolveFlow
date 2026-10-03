package com.resolveflow.shared.shopping;

import com.fasterxml.jackson.annotation.JsonProperty;
import java.time.Instant;
import java.util.List;

public final class FulfillmentWire {
    private FulfillmentWire() {}

    public record Event(
            String code,
            @JsonProperty("occurred_at") Instant occurredAt,
            @JsonProperty("source_version") long sourceVersion) {}

    public record Tracking(
            @JsonProperty("line_id") String lineId,
            String status,
            @JsonProperty("carrier_conclusion") String carrierConclusion,
            @JsonProperty("source_version") Long sourceVersion,
            List<Event> events) {}

    public record Fulfillment(
            @JsonProperty("order_id") String orderId,
            String status,
            boolean synthetic,
            Long version,
            @JsonProperty("updated_at") Instant updatedAt,
            List<Tracking> lines) {}

    public record LineAftercare(
            @JsonProperty("line_id") String lineId,
            String state,
            @JsonProperty("refunded_amount") Long refundedAmount,
            @JsonProperty("reserved_amount") Long reservedAmount) {}

    public record Trade(
            CheckoutWire.Purchase purchase,
            Fulfillment fulfillment,
            @JsonProperty("line_aftercare") List<LineAftercare> lineAftercare,
            @JsonProperty("can_ship") boolean canShip,
            @JsonProperty("blocked_reason") String blockedReason) {}

    public record Trades(
            List<Trade> items, @JsonProperty("next_cursor") String nextCursor) {}

    public record ShipRequest(
            @JsonProperty("expected_version")
            @tools.jackson.databind.annotation.JsonDeserialize(using = StrictVersion.class)
            Long expectedVersion) {}

    public record ShipCommand(
            @JsonProperty("merchant_id") String merchantId,
            String actor,
            @JsonProperty("idempotency_key") String idempotencyKey,

            @JsonProperty("expected_version")
            @tools.jackson.databind.annotation.JsonDeserialize(using = StrictVersion.class)
            Long expectedVersion) {}

    /** CAS versions are integer tokens; coercing decimals or strings could target another version. */
    public static class StrictVersion extends tools.jackson.databind.ValueDeserializer<Long> {
        @Override
        public Long deserialize(
                tools.jackson.core.JsonParser parser, tools.jackson.databind.DeserializationContext context) {
            if (parser.currentToken() != tools.jackson.core.JsonToken.VALUE_NUMBER_INT)
                throw new IllegalArgumentException("expected_version must be an integer");
            return parser.getLongValue();
        }
    }
}
