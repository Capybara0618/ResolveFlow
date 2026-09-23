package com.resolveflow.commerce.messaging;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Component;

/**
 * The loop that actually hands written results to the transport (C05.2b).
 *
 * <p>The mirror of the case side's loop (C05.1b), and separate from {@link ResultOutboxDeliveryService} for the
 * same two reasons: delivery behaviour can be tested by calling one method, and "when does it run" is one line
 * of configuration rather than a property of the logic. Off unless asked for — a demo that starts commerce
 * without a broker must still settle refunds and still record the outcomes it owes, and must not fill its outbox
 * with failures nobody asked for.
 *
 * <p>A pass that throws is logged and swallowed. The next tick tries again: a delivery loop that died on its
 * first database hiccup would stop delivering every later result too.
 */
@Component
@ConditionalOnProperty(name = "resolveflow.events.outbox.delivery-enabled", havingValue = "true")
public class ResultOutboxDeliveryLoop {

    private static final Logger LOG = LoggerFactory.getLogger(ResultOutboxDeliveryLoop.class);

    private final ResultOutboxDeliveryService delivery;
    private final int batchSize;

    public ResultOutboxDeliveryLoop(
            ResultOutboxDeliveryService delivery, @Value("${resolveflow.events.outbox.batch-size:50}") int batchSize) {
        this.delivery = delivery;
        this.batchSize = batchSize;
    }

    @Scheduled(fixedDelayString = "${resolveflow.events.outbox.poll-interval-ms:2000}")
    public void deliver() {
        try {
            ResultOutboxDeliveryService.Pass pass = delivery.deliverDue(batchSize);
            if (pass.published() > 0 || pass.failed() > 0 || pass.dead() > 0) {
                LOG.info(
                        "result outbox pass: {} published, {} failed, {} dead",
                        pass.published(),
                        pass.failed(),
                        pass.dead());
            }
        } catch (RuntimeException unexpected) {
            LOG.warn("result outbox pass failed; the next tick will try again", unexpected);
        }
    }
}
