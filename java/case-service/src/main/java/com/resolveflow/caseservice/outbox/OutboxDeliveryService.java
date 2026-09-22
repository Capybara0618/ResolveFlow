package com.resolveflow.caseservice.outbox;

import java.time.Clock;
import java.time.Duration;
import java.time.Instant;
import java.util.List;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Service;

/**
 * Getting written events onto the transport, at least once (docs/core-contracts.md:67).
 *
 * <p><b>At least once is the honest description of what this can promise.</b> A publish that the broker
 * accepted but whose acknowledgement was lost is indistinguishable from one that never arrived, and the
 * choice is between sending twice and losing an event. Sending twice is safe because the consumer keeps an
 * inbox keyed by the event id: the duplicate is recognised and dropped
 * (docs/domain-model.md:45 — inbox、业务结果和本地事件在同一事务). This service therefore never tries to be exactly
 * once; it tries to never give up.
 *
 * <p>Failure handling is deliberately three-state rather than two:
 *
 * <ul>
 *   <li>a failed attempt records the error and a next attempt time, so a broker outage slows delivery down
 *       instead of losing the event;
 *   <li>attempts beyond {@code max-attempts} move the row to {@code DEAD}, which keeps it: a dropped event is
 *       the fact an operator needs, and deleting it would erase the evidence;
 *   <li>and a delivery loop that finds nothing to do does nothing — no "success" is reported for work it did
 *       not attempt (docs/engineering.md:56).
 * </ul>
 */
@Service
public class OutboxDeliveryService {

    private static final Logger LOG = LoggerFactory.getLogger(OutboxDeliveryService.class);

    /** What one pass did, so a caller can report it rather than guess. */
    public record Pass(int published, int failed, int dead) {}

    private final OutboxRepository outbox;
    private final EventPublisher publisher;
    private final Clock clock;
    private final int maxAttempts;
    private final Duration baseBackoff;

    public OutboxDeliveryService(
            OutboxRepository outbox,
            EventPublisher publisher,
            Clock clock,
            @Value("${resolveflow.events.outbox.max-attempts:8}") int maxAttempts,
            @Value("${resolveflow.events.outbox.retry-base-seconds:5}") long baseBackoffSeconds) {
        this.outbox = outbox;
        this.publisher = publisher;
        this.clock = clock;
        this.maxAttempts = maxAttempts;
        this.baseBackoff = Duration.ofSeconds(baseBackoffSeconds);
    }

    /**
     * Publish what is due, oldest first.
     *
     * @param limit how many to attempt in one pass, so a backlog is worked through in bounded steps
     */
    public Pass deliverDue(int limit) {
        Instant now = Instant.now(clock);
        List<OutboxEvent> due = outbox.findDue(now, limit);
        int published = 0;
        int failed = 0;
        int dead = 0;
        for (OutboxEvent event : due) {
            switch (deliver(event)) {
                case PUBLISHED -> published++;
                case RETRYING -> failed++;
                case DEAD -> dead++;
            }
        }
        return new Pass(published, failed, dead);
    }

    private enum Outcome {
        PUBLISHED,
        RETRYING,
        DEAD
    }

    private Outcome deliver(OutboxEvent event) {
        try {
            publisher.publish(event.topic(), event.envelope(), event.eventId());
            outbox.markPublished(event.eventId(), Instant.now(clock));
            return Outcome.PUBLISHED;
        } catch (RuntimeException failure) {
            // Any failure is a delivery failure, not a reason to drop the event: a broker that is down, a
            // serialiser that rejects the envelope, a partition that is unavailable. The message is kept for
            // the next reader, truncated to what the column holds.
            String message = describe(failure);
            int attempts = event.attempts() + 1;
            if (attempts >= maxAttempts) {
                LOG.warn("outbox event {} gave up after {} attempts: {}", event.eventId(), attempts, message);
                outbox.markDead(event.eventId(), message);
                return Outcome.DEAD;
            }
            outbox.recordFailure(event.eventId(), message, Instant.now(clock).plus(backoffFor(attempts)));
            return Outcome.RETRYING;
        }
    }

    /**
     * How long to wait after {@code attempts} failures.
     *
     * <p>Doubling, capped by the attempt count reaching {@code maxAttempts} rather than by a ceiling: the row
     * is going to be given up on soon anyway, and a bounded progression is easier to reason about than a
     * truncated exponential.
     */
    Duration backoffFor(int attempts) {
        long multiplier = 1L << Math.min(attempts - 1, 10);
        return baseBackoff.multipliedBy(multiplier);
    }

    private static String describe(RuntimeException failure) {
        String message = failure.getMessage() == null ? failure.getClass().getSimpleName() : failure.getMessage();
        return message.length() <= 500 ? message : message.substring(0, 500);
    }
}
