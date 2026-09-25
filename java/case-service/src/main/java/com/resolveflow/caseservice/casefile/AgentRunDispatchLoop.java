package com.resolveflow.caseservice.casefile;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Component;

/**
 * C06.3a: the loop that hands each waiting case revision to the Agent.
 *
 * <p>C06.1c wrote the binding and the dispatch but nothing called them, so a case opened by a real customer
 * sat PENDING forever unless a human ran {@link AgentRunDispatch#dispatchDue}. This is the caller.
 *
 * <p>Separate from {@link AgentRunDispatch} for the reason the sibling loops in this service give
 * ({@link ExecutionDispatchLoop}, {@code OutboxDeliveryLoop}): the act can be tested by calling one method,
 * and "when does it run" is one line of configuration rather than a property of the logic. It is switched on
 * by the same property the execution loop uses, so a service that was asked to dispatch authorisations
 * dispatches runs as well, and no existing harness has to learn a second switch.
 *
 * <p><b>Off by default, and that is a real state rather than an oversight.</b> A case opened while this is
 * off has a committed binding that nothing delivers yet; the run is genuinely not queued, and no later reader
 * has to guess whether the Agent was told. Turning it on delivers the backlog, because the loop asks the
 * table what is still PENDING rather than being told at creation time.
 *
 * <p>A failure anywhere in a pass is logged and left for the next tick: the pass cannot throw, because a
 * scheduler that stops on the first bad row stops dispatching every case behind it — the one failure mode a
 * dispatch loop must not have.
 */
@Component
@ConditionalOnProperty(name = "resolveflow.dispatch.enabled", havingValue = "true")
public class AgentRunDispatchLoop {

    private static final Logger LOG = LoggerFactory.getLogger(AgentRunDispatchLoop.class);

    private final AgentRunDispatch dispatch;
    private final int batchSize;

    public AgentRunDispatchLoop(
            AgentRunDispatch dispatch, @Value("${resolveflow.dispatch.batch-size:50}") int batchSize) {
        this.dispatch = dispatch;
        this.batchSize = batchSize;
    }

    /**
     * One tick.
     *
     * <p>Started by the scheduler and callable directly. The interval is short because the work is a table
     * read plus at most one attempt per waiting row; waiting longer would only delay a run that is ready.
     */
    @Scheduled(fixedDelayString = "${resolveflow.dispatch.poll-interval-ms:2000}")
    public void tick() {
        try {
            AgentRunDispatch.Pass pass = dispatch.dispatchDue(batchSize);
            if (pass.dispatched() > 0 || pass.failed() > 0 || pass.skipped() > 0) {
                // Quiet when there was nothing to do: a loop that logs every two seconds forever is a loop
                // whose log nobody reads when it matters.
                LOG.info(
                        "run dispatch pass: {} delivered, {} not deliverable, {} failed",
                        pass.dispatched(),
                        pass.skipped(),
                        pass.failed());
            }
        } catch (RuntimeException unexpected) {
            // dispatchDue already contains its own per-row failures; reaching here means the pass itself broke
            // (a table that is gone, a repository that threw). The next tick tries again rather than this
            // tick killing the scheduler.
            LOG.warn("the run dispatch pass failed; the next tick will try again", unexpected);
        }
    }
}
