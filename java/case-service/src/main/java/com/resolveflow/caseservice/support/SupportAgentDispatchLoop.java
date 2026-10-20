package com.resolveflow.caseservice.support;

import jakarta.annotation.PreDestroy;
import java.util.concurrent.Executors;
import java.util.concurrent.atomic.AtomicBoolean;
import org.springframework.boot.autoconfigure.condition.ConditionalOnExpression;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Component;

/** One bounded worker keeps model latency off the shared Spring scheduler thread. */
@Component
@ConditionalOnExpression("${resolveflow.support-agent.enabled:${resolveflow.dispatch.enabled:false}}")
public class SupportAgentDispatchLoop {
    private final SupportAgentTurns turns;
    private final java.util.concurrent.ExecutorService worker = Executors.newSingleThreadExecutor(
            Thread.ofPlatform().name("support-agent-dispatch").daemon().factory());
    private final AtomicBoolean busy = new AtomicBoolean();

    public SupportAgentDispatchLoop(SupportAgentTurns turns) {
        this.turns = turns;
    }

    @Scheduled(fixedDelay = 1000)
    public void tick() {
        if (busy.compareAndSet(false, true))
            worker.submit(() -> {
                try {
                    turns.dispatchOne();
                } catch (RuntimeException e) {
                    org.slf4j.LoggerFactory.getLogger(getClass())
                            .warn("support dispatch failed: {}", e.getClass().getSimpleName());
                } finally {
                    busy.set(false);
                }
            });
    }

    @PreDestroy
    public void close() {
        worker.shutdown();
    }
}
