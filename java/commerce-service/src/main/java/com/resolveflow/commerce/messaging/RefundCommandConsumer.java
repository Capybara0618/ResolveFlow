package com.resolveflow.commerce.messaging;

import com.resolveflow.commerce.refund.RefundAcceptanceService;
import com.resolveflow.commerce.refund.RefundRejectedException;
import com.resolveflow.shared.core.CoreEnvelope;
import java.time.Clock;
import java.time.Instant;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import tools.jackson.databind.JsonNode;
import tools.jackson.databind.ObjectMapper;

/**
 * Consuming one refund command (C05.1b, docs/domain-model.md:47).
 *
 * <p>The order inside {@link #consume} is the design:
 *
 * <ol>
 *   <li><b>Parse.</b> A message that is not JSON is refused and recorded; there is nothing to verify.
 *   <li><b>Verify.</b> Signature and signer, before anything is trusted: the payload is only read as a
 *       command once it is known to have come from case-service.
 *   <li><b>Claim the event id.</b> The inbox claim happens before the effect and in the same transaction, so a
 *       redelivery that races the first one is answered "already claimed" and rolls back having changed
 *       nothing (docs/domain-model.md:45). The claim is one upsert rather than an insert that waits to be
 *       refused, so a duplicate is an answer rather than an exception ({@link EventInboxRepository#claim}).
 *       It does not remove the deadlock that concurrent deliveries of one event id can produce — see there.
 *   <li><b>Reserve.</b> The command goes through C04.2's acceptance path unchanged — the same payload-hash
 *       check, the same reservations. The consumer's job is to decide whether to call it, not to re-implement
 *       what it does. A domain refusal (the line is held, the amount is not the line's) is deliberately *not*
 *       filed as poison — C05.1b's decision — and the listener acknowledges it rather than retrying a decision
 *       that cannot change (C05.1c, {@link RefundCommandListener}).
 *   <li><b>Answer a refusal.</b> A refusal about a command this service understood is answered with a signed
 *       {@code RefundFailed} naming why, in this same transaction, and the delivery ends as {@code REFUSED}
 *       (C05.3b). Before that, the refusal ended the delivery with nothing written down, and the case — already
 *       told by its own records that a command was sent — waited in EXECUTING for an answer that could not
 *       come. See {@link #refuse}.
 * </ol>
 *
 * <p>A <em>protocol</em> refusal (the message is not JSON, the signature does not hold, the event type is not
 * this consumer's) is written to {@code event_rejection} and then reported to the transport as a failure. That
 * combination is deliberate: the row is what an operator reads, and the failed acknowledgement is what stops a
 * poison message from being acknowledged as if it had been applied
 * (docs/engineering.md:56 — 毒消息最终DLQ，需要操作台可追踪). A <em>domain</em> refusal is different and is
 * handled differently: see {@link #refuse}.
 */
@Service
public class RefundCommandConsumer {

    private static final Logger LOG = LoggerFactory.getLogger(RefundCommandConsumer.class);

    /** What one delivery was, once the transport has handed it to a consumer. */
    public enum Disposition {
        /** The command was new and its money is now reserved. */
        ACCEPTED,
        /** This event id was already applied: a duplicate, and harmless. */
        DUPLICATE
    }

    /** The one event type this consumer exists for. */
    private static final String COMMAND = CoreEnvelope.REFUND_REQUESTED;

    private final EventInboxRepository inbox;
    private final EventVerifier verifier;
    private final RefundAcceptanceService acceptance;
    private final EventRejectionLog rejections;
    private final Clock clock;
    private final ObjectMapper mapper;

    /** Where the answer to a refused command is written, in its own transaction (C05.3b). */
    private final RefusedCommandAnswer answers;

    public RefundCommandConsumer(
            EventInboxRepository inbox,
            EventVerifier verifier,
            RefundAcceptanceService acceptance,
            EventRejectionLog rejections,
            Clock clock,
            ObjectMapper mapper,
            RefusedCommandAnswer answers) {
        this.inbox = inbox;
        this.verifier = verifier;
        this.acceptance = acceptance;
        this.rejections = rejections;
        this.clock = clock;
        this.mapper = mapper;
        this.answers = answers;
    }

    /**
     * Consume one message.
     *
     * @param rawMessage the exact text the transport delivered
     */
    @Transactional
    public Disposition consume(String rawMessage) {
        JsonNode envelope = parse(rawMessage);
        JsonNode verified;
        try {
            verified = verifier.verify(envelope);
        } catch (EventVerifier.RefusedEventException refused) {
            reject(refused.refusal(), refused, envelope, rawMessage);
            throw refused;
        }

        String eventId = requiredText(verified, "event_id");
        String eventType = requiredText(verified, "event_type");
        String producer = requiredText(verified, "producer");
        if (!COMMAND.equals(eventType)) {
            // The consumer is subscribed to the command topic, so another core event type arriving here means a
            // routing or subscription mistake. Applied as if it were a command it would reserve money for a
            // message that never asked for any.
            EventVerifier.RefusedEventException notACommand = new EventVerifier.RefusedEventException(
                    EventVerifier.Refusal.WRONG_DIRECTION, "this consumer executes " + COMMAND + ", not " + eventType);
            reject(EventVerifier.Refusal.WRONG_DIRECTION, notACommand, verified, rawMessage);
            throw notACommand;
        }

        // The claim: one row per (consumer, event). The statement answers 1 when this delivery inserted the
        // row and 2 when it was already there, so a duplicate is an answer rather than an exception to catch
        // (the deadlock the exception-driven version produced under concurrent delivery, and the affected-row
        // trap the first upsert fell into, are both in EventInboxRepository.claim).
        if (inbox.claim(
                        EventTrustConfiguration.REFUND_COMMAND_CONSUMER,
                        eventId,
                        eventType,
                        producer,
                        Disposition.ACCEPTED.name(),
                        null,
                        Instant.now(clock))
                != 1) {
            return Disposition.DUPLICATE;
        }

        JsonNode payload = verified.get("payload");
        if (payload == null || !payload.isObject()) {
            throw new EventVerifier.RefusedEventException(
                    EventVerifier.Refusal.MALFORMED, "a refund command has a payload object");
        }

        RefundAcceptanceService.Receipt receipt;
        try {
            receipt = acceptance.accept(eventId, payload);
        } catch (RefundRejectedException refused) {
            throw refuse(refused, verified, rawMessage);
        }
        return receipt.replayed() ? Disposition.DUPLICATE : Disposition.ACCEPTED;
    }

    /**
     * Tell the case why its command was refused, then let the refusal end this delivery (C05.3b).
     *
     * <p>What was missing before this: the refusal rolled the claim back and the listener acknowledged the
     * delivery as terminal, which it has to do — asking again does not change the world, and the retries took
     * the line's lock each time (C05.1c). So the command was gone, and the case, which had already written a row
     * saying it sent one and consumed the authorisation, waited in EXECUTING for an answer that could not come.
     * The listener's own comment said "carrying the refusal back to the case is C05.2's result projection"; this
     * is that projection's input, arriving one sub-step late.
     *
     * <p><b>Why the answer is written in its own transaction.</b> This one is about to roll back — and it must:
     * a refusal raised after {@code operations.insert} (the ledger then refuses the reservation) would otherwise
     * commit half a reservation, which is precisely the state the domain forbids. Marking the refusal
     * {@code noRollbackFor} would do that, so the answer goes through {@link RefusedCommandAnswer}, whose
     * {@code REQUIRES_NEW} transaction survives this one. The cost is the at-least-once one this project already
     * accepts: if the acknowledgement is lost the delivery is answered a second time, which the case records as a
     * stale fact about an operation it has already decided (nothing moves twice, because no money was reserved).
     *
     * <p>Two kinds of refusal reach here, and they are not the same thing:
     *
     * <ul>
     *   <li><b>About a command this service understood</b> ({@link RefundRejectedException#command()} is set):
     *       the case is owed an answer and gets one — {@code RefundFailed} naming the reason, correlated through
     *       the operation id the case itself fixed, so the projection returns it to a person instead of leaving
     *       it executing.
     *   <li><b>About a message that never became a command</b> (malformed, or a payload hash that does not cover
     *       its own members): there is no operation id to answer about, so nothing is sent. It is filed as a
     *       protocol rejection instead, which is what keeps it visible to an operator rather than a WARN line
     *       that rotates away. This service genuinely cannot tell the case anything it could correlate.
     * </ul>
     */
    private RefundRejectedException refuse(RefundRejectedException refused, JsonNode envelope, String rawMessage) {
        if (refused.command() == null) {
            reject(EventVerifier.Refusal.MALFORMED, refused, envelope, rawMessage);
            return refused;
        }
        String eventId = answers.record(refused.command(), refused.error());
        LOG.warn(
                "refused a core event by the domain: {} ({}); the case was answered with result {}",
                refused.error(),
                refused.getMessage(),
                eventId);
        return refused;
    }

    private JsonNode parse(String rawMessage) {
        if (rawMessage == null || rawMessage.isBlank()) {
            EventVerifier.RefusedEventException empty = new EventVerifier.RefusedEventException(
                    EventVerifier.Refusal.MALFORMED, "an empty message is not an event");
            reject(EventVerifier.Refusal.MALFORMED, empty, null, rawMessage);
            throw empty;
        }
        try {
            return mapper.readTree(rawMessage);
        } catch (RuntimeException notJson) {
            EventVerifier.RefusedEventException unparseable = new EventVerifier.RefusedEventException(
                    EventVerifier.Refusal.MALFORMED, "the message is not JSON: " + notJson.getMessage());
            reject(EventVerifier.Refusal.MALFORMED, unparseable, null, rawMessage);
            throw unparseable;
        }
    }

    /** Keep the refused message and why, in its own transaction so the consumer's rollback cannot erase it. */
    private void reject(EventVerifier.Refusal refusal, RuntimeException cause, JsonNode envelope, String rawMessage) {
        rejections.record(
                EventTrustConfiguration.REFUND_COMMAND_CONSUMER, refusal, envelope, rawMessage, cause.getMessage());
        LOG.warn("refused a core event: {} ({})", refusal.name(), cause.getMessage());
    }

    private static String requiredText(JsonNode envelope, String member) {
        JsonNode value = envelope.get(member);
        if (value == null || !value.isString() || value.stringValue().isBlank()) {
            throw new EventVerifier.RefusedEventException(
                    EventVerifier.Refusal.MALFORMED, "the envelope has no usable " + member);
        }
        return value.stringValue();
    }
}
