package com.resolveflow.commerce.catalog;

import java.sql.Timestamp;
import java.time.Clock;
import java.time.Instant;
import java.time.temporal.ChronoUnit;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Component;
import org.springframework.transaction.PlatformTransactionManager;
import org.springframework.transaction.support.TransactionTemplate;

/** Persistent local payment simulation; deliberately has no public fault switches. */
@Component
public class SimulatedCheckoutProvider {
    private final JdbcTemplate jdbc;
    private final Clock clock;
    private final TransactionTemplate tx;

    public SimulatedCheckoutProvider(JdbcTemplate jdbc, Clock clock, PlatformTransactionManager manager) {
        this.jdbc = jdbc;
        this.clock = clock;
        this.tx = new TransactionTemplate(manager);
        this.tx.setPropagationBehavior(org.springframework.transaction.TransactionDefinition.PROPAGATION_REQUIRES_NEW);
    }

    public record Receipt(String attemptId, long amount, String status, Instant finishedAt) {}

    public static class Uncertain extends RuntimeException {
        private static final long serialVersionUID = 1L;
    }

    public Receipt charge(String attemptId, long amount) {
        return tx.execute(status -> {
            jdbc.update(
                    "INSERT INTO simulated_checkout_receipt(attempt_id,total_amount,status,finished_at) VALUES(?,?,'SUCCEEDED',?) ON DUPLICATE KEY UPDATE attempt_id=attempt_id",
                    attemptId,
                    amount,
                    Timestamp.from(Instant.now(clock).truncatedTo(ChronoUnit.MICROS)));
            var receipt = lookup(attemptId);
            if (receipt.amount() != amount) throw new IllegalStateException("simulated payment amount conflict");
            return receipt;
        });
    }

    public Receipt lookup(String attemptId) {
        var rows = jdbc.query(
                "SELECT * FROM simulated_checkout_receipt WHERE attempt_id=?",
                (rs, n) -> new Receipt(
                        rs.getString("attempt_id"),
                        rs.getLong("total_amount"),
                        rs.getString("status"),
                        rs.getTimestamp("finished_at").toInstant()),
                attemptId);
        return rows.isEmpty() ? null : rows.getFirst();
    }
}
