package com.resolveflow.caseservice.outbox;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Component;

/**
 * The loop that actually delivers written events (C05.1b).
 *
 * <p>Kept separate from {@link OutboxDeliveryService} so the delivery behaviour can be tested by calling one
 * method, and so "when does it run" is one line of configuration rather than a property of the logic. Off unless
 * asked for: two services both running a delivery loop for the same topic would be harmless (the row update is
 * state-guarded) but confusing, and a demo that starts a broker-less service should not fill its outbox with
 * failures nobody asked for.
 *
 * <p>A pass that throws is logged and swallowed. The next tick tries again: an outbox loop that died on its
 * first database hiccup would stop delivering every later event too.
 */
@Component
@ConditionalOnProperty(name = "resolveflow.events.outbox.delivery-enabled", havingValue = "true")
public class OutboxDeliveryLoop {

    private static final Logger LOG = LoggerFactory.getLogger(OutboxDeliveryLoop.class);

    private final OutboxDeliveryService delivery;
    private final int batchSize;

    public OutboxDeliveryLoop(
            OutboxDeliveryService delivery,
            @org.springframework.beans.factory.annotation.Value("${resolveflow.events.outbox.batch-size:50}")
                    int batchSize) {
        this.delivery = delivery;
        this.batchSize = batchSize;
    }

    @Scheduled(fixedDelayString = "${resolveflow.events.outbox.poll-interval-ms:2000}")
    public void deliver() {
        try {
            OutboxDeliveryService.Pass pass = delivery.deliverDue(batchSize);
            if (pass.published() > 0 || pass.failed() > 0 || pass.dead() > 0) {
                LOG.info("outbox pass: {} published, {} failed, {} dead", pass.published(), pass.failed(), pass.dead());
            }
        } catch (RuntimeException unexpected) {
            LOG.warn("outbox pass failed; the next tick will try again", unexpected);
        }
    }
}
