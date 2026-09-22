package com.resolveflow.caseservice.outbox;

import java.time.Instant;

/**
 * One outbox row: a signed envelope plus how far its delivery has got (V12__case_event_outbox.sql).
 *
 * <p>{@code envelope} is the exact text that will be published, not a model to be re-rendered. That is what
 * makes the signature checkable by the consumer: they verify the bytes this row holds.
 */
public record OutboxEvent(
        String eventId,
        String eventType,
        int schemaVersion,
        String merchantId,
        String topic,
        String producer,
        String envelope,
        String signature,
        String signingKeyId,
        String status,
        int attempts,
        String lastError,
        Instant nextAttemptAt,
        Instant createdAt,
        Instant publishedAt) {

    public boolean isPublished() {
        return "PUBLISHED".equals(status);
    }

    public boolean isDead() {
        return "DEAD".equals(status);
    }
}
