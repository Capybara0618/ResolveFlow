package com.resolveflow.caseservice.result;

import java.time.Clock;
import java.time.Instant;
import java.util.UUID;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Propagation;
import org.springframework.transaction.annotation.Transactional;
import tools.jackson.databind.JsonNode;

/**
 * Keeping a refused result, in a transaction of its own (V13, {@code case_result_rejection}).
 *
 * <p>A separate bean rather than a private method on {@link CaseResultConsumer} for one reason: the consumer's
 * transaction is about to fail, and a record written inside it would roll back with the failure. The row an
 * operator needs would be exactly the row that disappeared — so the write runs in its own transaction
 * ({@code REQUIRES_NEW}), which only works when the call goes through a proxy. A self-invoked
 * {@code REQUIRES_NEW} method silently joins the caller's transaction, and the log would look fine while the
 * evidence vanished. Commerce's {@code EventRejectionLog} exists for the same reason.
 */
@Service
public class CaseResultRejectionLog {

    private final CaseResultInboxRepository inbox;
    private final Clock clock;

    public CaseResultRejectionLog(CaseResultInboxRepository inbox, Clock clock) {
        this.inbox = inbox;
        this.clock = clock;
    }

    /** Record one refusal; the message itself is truncated to what the column holds but never dropped. */
    @Transactional(propagation = Propagation.REQUIRES_NEW)
    public void record(
            String consumer, CaseResultVerifier.Refusal refusal, JsonNode envelope, String rawMessage, String detail) {
        inbox.reject(
                UUID.randomUUID().toString(),
                consumer,
                envelope == null ? null : text(envelope, "event_id"),
                envelope == null ? null : text(envelope, "topic"),
                refusal.name(),
                truncate(detail == null || detail.isBlank() ? refusal.description() : detail, 500),
                truncate(rawMessage, 4000),
                Instant.now(clock));
    }

    private static String text(JsonNode node, String member) {
        JsonNode value = node.get(member);
        return value != null && value.isString() ? value.stringValue() : null;
    }

    private static String truncate(String text, int limit) {
        if (text == null) {
            return null;
        }
        return text.length() <= limit ? text : text.substring(0, limit);
    }
}
