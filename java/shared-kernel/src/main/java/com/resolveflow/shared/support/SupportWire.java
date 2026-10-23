package com.resolveflow.shared.support;

import com.fasterxml.jackson.annotation.JsonInclude;
import com.fasterxml.jackson.annotation.JsonProperty;
import java.time.Instant;
import java.util.List;
import java.util.Map;

public final class SupportWire {
    private SupportWire() {}

    public record Open(@JsonProperty("line_id") String lineId) {}

    public record Send(@JsonProperty("expected_version") Long expectedVersion, String text, String recipient) {}

    public record Handoff(
            @JsonProperty("expected_version") Long expectedVersion,
            String summary,
            @JsonProperty("shared_message_ids") List<String> sharedMessageIds,

            @JsonProperty("assistant_message_id") @JsonInclude(JsonInclude.Include.NON_NULL)
            String assistantMessageId) {
        public Handoff(Long expectedVersion, String summary, List<String> sharedMessageIds) {
            this(expectedVersion, summary, sharedMessageIds, null);
        }
    }

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
            @JsonProperty("created_at") Instant createdAt,
            @JsonInclude(JsonInclude.Include.NON_NULL) Assistant assistant) {
        public Message(
                String messageId,
                long sequence,
                String author,
                String recipient,
                String text,
                String ticketId,
                Instant createdAt) {
            this(messageId, sequence, author, recipient, text, ticketId, createdAt, null);
        }
    }

    public record Assistant(
            @JsonProperty("run_id") String runId,
            String mode,
            List<Map<String, Object>> citations,
            @JsonProperty("handoff_summary") String handoffSummary,

            @JsonProperty("refund_summary") @JsonInclude(JsonInclude.Include.NON_NULL)
            String refundSummary) {
        public Assistant(String runId, String mode, List<Map<String, Object>> citations, String handoffSummary) {
            this(runId, mode, citations, handoffSummary, null);
        }
    }

    public record AssistantTurn(@JsonProperty("run_id") String runId, String status, String reason) {}

    public record Ticket(
            @JsonProperty("ticket_id") String ticketId,
            String status,
            String summary,
            @JsonProperty("shared_messages") List<Message> sharedMessages,
            @JsonInclude(JsonInclude.Include.NON_NULL) Assistant report) {
        public Ticket(String id, String status, String summary, List<Message> messages) {
            this(id, status, summary, messages, null);
        }
    }

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
            @JsonProperty("next_before_sequence") Long nextBeforeSequence,

            @JsonProperty("assistant_turn") @JsonInclude(JsonInclude.Include.NON_NULL)
            AssistantTurn assistantTurn) {
        public Conversation(
                String id,
                String merchant,
                String store,
                String order,
                String line,
                Product product,
                long version,
                Ticket ticket,
                List<Message> messages,
                Long next) {
            this(id, merchant, store, order, line, product, version, ticket, messages, next, null);
        }
    }

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
