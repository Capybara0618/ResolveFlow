package com.resolveflow.caseservice.casefile;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Component;

/**
 * The loop that consumes approved authorisations (C05.2a).
 *
 * <p>Separate from {@link AuthorizationConsumptionService} for the same reason the outbox loop is separate from
 * its delivery service: the act can be tested by calling one method, and "when does it run" is one line of
 * configuration instead of a property of the logic. Off unless asked for — a service started without it still
 * approves, still refuses, still cancels, and simply leaves the approved authorisation waiting, which is the
 * honest state when nobody asked for money to be dispatched.
 *
 * <p>Each candidate is consumed in its own transaction, and a candidate that fails is logged and left for the
 * next tick rather than stopping the pass: a batch that died on its first bad row would stop dispatching every
 * approval behind it, which is the one failure mode a dispatch loop must not have. The outbox delivery loop
 * makes the other half of the promise — the command it writes is retried until the broker takes it (C05.1a).
 */
@Component
@ConditionalOnProperty(name = "resolveflow.dispatch.enabled", havingValue = "true")
public class ExecutionDispatchLoop {

    private static final Logger LOG = LoggerFactory.getLogger(ExecutionDispatchLoop.class);

    private final AuthorizationConsumptionService consumption;
    private final AuthorizationRepository authorizations;
    private final int batchSize;

    public ExecutionDispatchLoop(
            AuthorizationConsumptionService consumption,
            AuthorizationRepository authorizations,
            @Value("${resolveflow.dispatch.batch-size:50}") int batchSize) {
        this.consumption = consumption;
        this.authorizations = authorizations;
        this.batchSize = batchSize;
    }

    @Scheduled(fixedDelayString = "${resolveflow.dispatch.poll-interval-ms:2000}")
    public void dispatch() {
        try {
            Pass pass = dispatchDue(batchSize);
            if (pass.dispatched() > 0 || pass.skipped() > 0 || pass.failed() > 0) {
                LOG.info(
                        "dispatch pass: {} consumed, {} not applicable, {} failed",
                        pass.dispatched(),
                        pass.skipped(),
                        pass.failed());
            }
        } catch (RuntimeException unexpected) {
            LOG.warn("dispatch pass failed; the next tick will try again", unexpected);
        }
    }

    /** One pass, callable without the scheduler (tests, and a manual run of a backlog). */
    public Pass dispatchDue(int limit) {
        int dispatched = 0;
        int skipped = 0;
        int failed = 0;
        for (AuthorizationRepository.DispatchCandidate candidate : authorizations.findAwaitingDispatch(limit)) {
            try {
                AuthorizationConsumptionService.Consumption outcome = consumption.consume(candidate);
                if (outcome.dispatched()) {
                    dispatched++;
                    LOG.info(
                            "authorisation {} consumed: case {} is executing, operation {}, event {}",
                            outcome.authorizationId(),
                            candidate.caseId(),
                            outcome.operationId(),
                            outcome.eventId());
                } else {
                    skipped++;
                    LOG.info(
                            "authorisation {} was not consumed: {}",
                            outcome.authorizationId(),
                            outcome.skippedBecause());
                }
            } catch (RuntimeException failure) {
                failed++;
                LOG.warn(
                        "authorisation {} could not be consumed; the next tick will try again",
                        candidate.authorizationId(),
                        failure);
            }
        }
        return new Pass(dispatched, skipped, failed);
    }

    /** What one pass did, so a caller (or a test) can assert on it instead of on the log. */
    public record Pass(int dispatched, int skipped, int failed) {}
}
