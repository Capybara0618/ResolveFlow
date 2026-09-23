package com.resolveflow.commerce.refund;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Component;

/**
 * The loop that sends reserved refunds to the provider (C05.2c).
 *
 * <p>Kept separate from {@link RefundDispatchService} for the same reason every other loop in this project is:
 * the act can be tested by calling one method, and "when does it run" is one line of configuration rather than
 * a property of the logic. Off unless asked for — a service started without it still accepts commands, still
 * reserves money and still writes the operations it owes, and simply has not been told to send any of them
 * yet, which is the honest state when nobody asked for money to move.
 *
 * <p><b>Why this loop had to exist.</b> C04.3 built the call, C04.2 built the reservation, and every test of
 * both called {@code dispatch(id)} itself. Nothing in {@code src/main} did — so in a real deployment a command
 * reserved the money and the refund stopped there: no provider request, no result event, and a case waiting in
 * {@code EXECUTING} forever. This is the entry point the ledger said would have to come from "C05 或 C11".
 *
 * <p>A pass that throws is logged and swallowed. The next tick tries again: a loop that died on its first
 * database hiccup would stop sending every later refund too.
 */
@Component
@ConditionalOnProperty(name = "resolveflow.refund.dispatch-enabled", havingValue = "true")
public class RefundDispatchLoop {

    private static final Logger LOG = LoggerFactory.getLogger(RefundDispatchLoop.class);

    private final RefundDispatchService dispatch;
    private final int batchSize;

    public RefundDispatchLoop(
            RefundDispatchService dispatch, @Value("${resolveflow.refund.batch-size:50}") int batchSize) {
        this.dispatch = dispatch;
        this.batchSize = batchSize;
    }

    @Scheduled(fixedDelayString = "${resolveflow.refund.poll-interval-ms:2000}")
    public void sendReserved() {
        try {
            RefundDispatchService.Pass pass = dispatch.dispatchDue(batchSize);
            if (pass.attempted() > 0) {
                LOG.info(
                        "refund dispatch pass: {} reserved operation(s) sent to the provider, {} could not be"
                                + " sent and will be retried",
                        pass.attempted() - pass.failed(),
                        pass.failed());
            }
        } catch (RuntimeException unexpected) {
            LOG.warn("refund dispatch pass failed; the next tick will try again", unexpected);
        }
    }
}
