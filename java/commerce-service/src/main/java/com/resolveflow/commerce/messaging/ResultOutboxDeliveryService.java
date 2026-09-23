package com.resolveflow.commerce.messaging;

import java.time.Clock;
import java.time.Duration;
import java.time.Instant;
import java.util.List;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Service;

/**
 * Getting the results the case is owed onto the transport, at least once (C05.2b, docs/core-contracts.md:67).
 *
 * <p><b>At least once is the honest description of what this can promise.</b> A publish the broker accepted but
 * whose acknowledgement was lost is indistinguishable from one that never arrived, and the choice is between
 * sending twice and losing the outcome of a refund. Sending twice is safe because the case keeps an inbox keyed
 * by the event id — and, for results, because the payload carries {@code aggregate_version}: a duplicate is the
 * same version and changes nothing, which is what lets the case sort out an outcome that arrives after a later
 * one (docs/domain-model.md:45, `contracts/core/README.md` decision 5). This service therefore never tries to be
 * exactly once; it tries to never give up.
 *
 * <p>Failure handling is three-state rather than two, exactly as on the case side (C05.1a):
 *
 * <ul>
 *   <li>a failed attempt records the error and a next attempt time, so a broker outage slows delivery down
 *       instead of losing the outcome;
 *   <li>attempts beyond {@code max-attempts} move the row to {@code DEAD}, which keeps it: a result the case
 *       never heard is the fact an operator needs, and deleting it would erase the evidence;
 *   <li>and a pass that finds nothing to do does nothing — no "success" is reported for work it did not attempt
 *       (docs/engineering.md:56).
 * </ul>
 *
 * <p>A refund is already settled by the time anything here runs: the money moved, and the row this service
 * delivers was written in the transaction that moved it. Delivery therefore never touches the ledger, the
 * operation or the line — it only changes how a signed document travels, which is why a transport outage is
 * survivable at all.
 */
@Service
public class ResultOutboxDeliveryService {

    private static final Logger LOG = LoggerFactory.getLogger(ResultOutboxDeliveryService.class);

    /** What one pass did, so a caller can report it rather than guess. */
    public record Pass(int published, int failed, int dead) {}

    private final ResultOutboxRepository outbox;
    private final EventPublisher publisher;
    private final Clock clock;
    private final int maxAttempts;
    private final Duration baseBackoff;

    public ResultOutboxDeliveryService(
            ResultOutboxRepository outbox,
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
        List<ResultOutboxRepository.ResultEvent> due = outbox.findDue(now, limit);
        int published = 0;
        int failed = 0;
        int dead = 0;
        for (ResultOutboxRepository.ResultEvent event : due) {
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

    private Outcome deliver(ResultOutboxRepository.ResultEvent event) {
        try {
            publisher.publish(event.topic(), event.envelope(), event.eventId());
            outbox.markPublished(event.eventId(), Instant.now(clock));
            return Outcome.PUBLISHED;
        } catch (RuntimeException failure) {
            // Any failure is a delivery failure, not a reason to drop the outcome: a broker that is down, a
            // partition that is unavailable, a serialiser that rejects the document. The row is kept for the next
            // reader, with the message truncated to what the column holds.
            String message = describe(failure);
            int attempts = event.attempts() + 1;
            if (attempts >= maxAttempts) {
                LOG.warn("result event {} gave up after {} attempts: {}", event.eventId(), attempts, message);
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
     * <p>Doubling, capped by the attempt count reaching {@code maxAttempts} rather than by a ceiling: the row is
     * going to be given up on soon anyway, and a bounded progression is easier to reason about than a truncated
     * exponential.
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
