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

    public record Trade(
            CheckoutWire.Purchase purchase,
            Fulfillment fulfillment,
            @JsonProperty("can_ship") boolean canShip,
            @JsonProperty("blocked_reason") String blockedReason) {}

    public record Trades(
            List<Trade> items, @JsonProperty("next_cursor") String nextCursor) {}

    public record ShipRequest(
            @JsonProperty("expected_version") Long expectedVersion) {}

    public record ShipCommand(
            @JsonProperty("merchant_id") String merchantId,
            String actor,
            @JsonProperty("idempotency_key") String idempotencyKey,
            @JsonProperty("expected_version") Long expectedVersion) {}
}
