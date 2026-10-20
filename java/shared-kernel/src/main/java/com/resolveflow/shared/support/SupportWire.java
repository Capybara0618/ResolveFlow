package com.resolveflow.shared.support;

import com.fasterxml.jackson.annotation.JsonProperty;
import java.time.Instant;
import java.util.List;

public final class SupportWire {
    private SupportWire() {}

    public record Open(@JsonProperty("line_id") String lineId) {}

    public record Send(@JsonProperty("expected_version") Long expectedVersion, String text, String recipient) {}

    public record Handoff(
            @JsonProperty("expected_version") Long expectedVersion,
            String summary,
            @JsonProperty("shared_message_ids") List<String> sharedMessageIds) {}

    public record Reply(@JsonProperty("expected_version") Long expectedVersion, String text, String kind) {}

    public record Resolve(@JsonProperty("expected_version") Long expectedVersion) {}

    public record Product(
            String name,
            String variant,
            @JsonProperty("asset_key") String assetKey,
            int quantity,
            @JsonProperty("amount_minor") long amountMinor,
            String currency) {}

    public record Message(
            @JsonProperty("message_id") String messageId,
            long sequence,
            String author,
            String recipient,
            String text,
            @JsonProperty("ticket_id") String ticketId,
            @JsonProperty("created_at") Instant createdAt) {}

    public record Ticket(
            @JsonProperty("ticket_id") String ticketId,
            String status,
            String summary,
            @JsonProperty("shared_messages") List<Message> sharedMessages) {}

    public record Conversation(
            @JsonProperty("conversation_id") String conversationId,
            @JsonProperty("merchant_id") String merchantId,
            @JsonProperty("store_name") String storeName,
            @JsonProperty("order_id") String orderId,
            @JsonProperty("line_id") String lineId,
            Product product,
            long version,
            Ticket ticket,
            List<Message> messages,
            @JsonProperty("next_before_sequence") Long nextBeforeSequence) {}

    public record TicketDetail(
            @JsonProperty("conversation_id") String conversationId,
            @JsonProperty("merchant_id") String merchantId,
            @JsonProperty("store_name") String storeName,
            @JsonProperty("order_id") String orderId,
            @JsonProperty("line_id") String lineId,
            Product product,
            long version,
            Ticket ticket,
            List<Message> messages,
            @JsonProperty("next_before_sequence") Long nextBeforeSequence) {}

    public record Page<T>(
            List<T> items, @JsonProperty("next_before") Long nextBefore) {}
}
