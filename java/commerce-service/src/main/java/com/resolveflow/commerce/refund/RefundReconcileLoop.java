package com.resolveflow.commerce.refund;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Component;

/**
 * The loop that resolves refunds whose outcome is still unknown (C05.2c).
 *
 * <p>The reconciliation half of C04.3, and the entry point it was missing: {@code reconcileDue} had no caller
 * in {@code src/main}, so "an UNKNOWN is retried until the provider can say what happened" was a property of
 * the tests rather than of the service. Until it runs, a lost response stays UNKNOWN for good — the reservation
 * is kept (correctly), and the case sits in {@code RECONCILING} waiting for a resolution that never comes.
 *
 * <p><b>Its own switch, not the dispatch loop's.</b> The two passes look alike but ask different things:
 * dispatching <em>requests</em> money movement, reconciling only <em>reads</em> what happened. An operator
 * stopping money requests during an incident must still be able to let reconciliation finish the refunds that
 * are already in flight, so sharing one switch would remove a decision they actually need.
 *
 * <p>A pass that throws is logged and swallowed, like every other loop here: the next tick tries again, and one
 * bad operation must not stop the ones behind it.
 */
@Component
@ConditionalOnProperty(name = "resolveflow.refund.reconcile-enabled", havingValue = "true")
public class RefundReconcileLoop {

    private static final Logger LOG = LoggerFactory.getLogger(RefundReconcileLoop.class);

    private final RefundDispatchService dispatch;
    private final int batchSize;

    public RefundReconcileLoop(
            RefundDispatchService dispatch, @Value("${resolveflow.refund.batch-size:50}") int batchSize) {
        this.dispatch = dispatch;
        this.batchSize = batchSize;
    }

    @Scheduled(fixedDelayString = "${resolveflow.refund.poll-interval-ms:2000}")
    public void reconcileUnknown() {
        try {
            int looked = dispatch.reconcileDue(batchSize);
            if (looked > 0) {
                LOG.info("refund reconciliation pass: {} unresolved operation(s) asked about", looked);
            }
        } catch (RuntimeException unexpected) {
            LOG.warn("refund reconciliation pass failed; the next tick will try again", unexpected);
        }
    }
}
