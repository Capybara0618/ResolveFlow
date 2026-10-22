package com.resolveflow.commerce.catalog;

import org.springframework.beans.factory.annotation.Value;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Component;

@Component
@ConditionalOnProperty(name = "resolveflow.checkout.recovery-enabled", havingValue = "true")
public class CheckoutRecoveryLoop {
    private static final org.slf4j.Logger LOG = org.slf4j.LoggerFactory.getLogger(CheckoutRecoveryLoop.class);
    private final CheckoutRecoveryService recovery;
    private final int size;

    public CheckoutRecoveryLoop(
            CheckoutRecoveryService recovery, @Value("${resolveflow.checkout.recovery-batch-size:20}") int size) {
        if (size < 1 || size > 100) throw new IllegalArgumentException("recovery batch must be 1–100");
        this.recovery = recovery;
        this.size = size;
    }

    @Scheduled(
            fixedDelayString = "${resolveflow.checkout.recovery-poll-ms:2000}",
            initialDelayString = "${resolveflow.checkout.recovery-poll-ms:2000}")
    public void tick() {
        try {
            var pass = recovery.tick(size);
            if (pass.expired() > 0 || pass.attempted() > 0)
                LOG.info(
                        "checkout recovery expired={} checked={} resolved={} failed={}",
                        pass.expired(),
                        pass.attempted(),
                        pass.resolved(),
                        pass.failed());
        } catch (RuntimeException unavailable) {
            LOG.warn(
                    "checkout recovery pass failed; next tick will retry ({})",
                    unavailable.getClass().getSimpleName());
        }
    }
}
