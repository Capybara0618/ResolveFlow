package com.resolveflow.commerce.catalog;

import io.micrometer.core.instrument.MeterRegistry;
import java.sql.Timestamp;
import java.time.Clock;
import java.time.Instant;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Service;

@Service
public class CheckoutRecoveryService {
    public record Pass(int expired, int attempted, int resolved, int failed) {}

    private record Attempt(String id, String draft, String merchant, String customer) {}

    private static final org.slf4j.Logger LOG = org.slf4j.LoggerFactory.getLogger(CheckoutRecoveryService.class);
    private final JdbcTemplate jdbc;
    private final CheckoutPayments payments;
    private final SimulatedCheckoutProvider provider;
    private final Clock clock;
    private final MeterRegistry metrics;

    public CheckoutRecoveryService(
            JdbcTemplate jdbc,
            CheckoutPayments payments,
            SimulatedCheckoutProvider provider,
            Clock clock,
            MeterRegistry metrics) {
        this.jdbc = jdbc;
        this.payments = payments;
        this.provider = provider;
        this.clock = clock;
        this.metrics = metrics;
    }
    /** Each statement/settlement is a short transaction; provider lookup never holds a business lock. */
    public Pass tick(int size) {
        if (size < 1 || size > 100) throw new IllegalArgumentException("recovery batch must be 1–100");
        var now = Timestamp.from(Instant.now(clock));
        var next = Timestamp.from(Instant.now(clock).plusSeconds(30));
        int expired = jdbc.update(
                "UPDATE checkout_draft SET status='CANCELLED',close_reason='EXPIRED' WHERE status='WAITING_PAYMENT' AND expires_at<=? ORDER BY expires_at,draft_id LIMIT ?",
                now,
                size);
        var due = jdbc.query(
                "SELECT a.attempt_id,a.draft_id,d.merchant_id,d.buyer_id FROM checkout_payment_attempt a JOIN checkout_draft d ON d.draft_id=a.draft_id WHERE a.status='UNKNOWN' AND d.status='PAYMENT_PENDING' AND a.next_reconcile_at<=? ORDER BY a.next_reconcile_at,a.attempt_id LIMIT ?",
                (r, n) -> new Attempt(
                        r.getString("attempt_id"),
                        r.getString("draft_id"),
                        r.getString("merchant_id"),
                        r.getString("buyer_id")),
                now,
                size);
        int attempted = 0, resolved = 0, failed = 0;
        for (var attempt : due) {
            // Persistent backoff is also a conditional claim shared by competing/restarted workers.
            if (jdbc.update(
                            "UPDATE checkout_payment_attempt SET next_reconcile_at=?,reconcile_count=reconcile_count+1,last_reconcile_error=NULL WHERE attempt_id=? AND status='UNKNOWN' AND next_reconcile_at<=?",
                            next,
                            attempt.id(),
                            now)
                    != 1) continue;
            attempted++;
            try {
                var receipt = provider.lookup(attempt.id());
                if (receipt == null) {
                    metrics.counter("resolveflow.checkout.recovery", "outcome", "unresolved")
                            .increment();
                    continue;
                }
                if (!attempt.id().equals(receipt.attemptId()))
                    throw new IllegalStateException("original attempt mismatch");
                payments.settle(attempt.draft(), attempt.merchant(), attempt.customer(), receipt);
                resolved++;
                metrics.counter("resolveflow.checkout.recovery", "outcome", "resolved")
                        .increment();
            } catch (RuntimeException problem) {
                failed++;
                String reason =
                        problem instanceof ShoppingService.Refused ? "RESULT_CONFLICT" : "LOOKUP_OR_PUBLICATION_FAILED";
                try {
                    jdbc.update(
                            "UPDATE checkout_payment_attempt SET last_reconcile_error=? WHERE attempt_id=? AND status='UNKNOWN'",
                            reason,
                            attempt.id());
                } catch (RuntimeException unavailable) {
                    LOG.warn("checkout recovery diagnostic could not be persisted for attempt {}", attempt.id());
                }
                metrics.counter("resolveflow.checkout.recovery", "outcome", "failed")
                        .increment();
                LOG.warn("checkout recovery deferred attempt {} reason {}", attempt.id(), reason);
            }
        }
        if (expired > 0)
            metrics.counter("resolveflow.checkout.recovery", "outcome", "expired")
                    .increment(expired);
        return new Pass(expired, attempted, resolved, failed);
    }
}
