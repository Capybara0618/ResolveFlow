package com.resolveflow.spike;

import com.resolveflow.spike.entitlement.EntitlementRows.EntitlementRow;
import com.resolveflow.spike.entitlement.EntitlementRows.LedgerRow;
import com.resolveflow.spike.entitlement.EntitlementService;
import com.resolveflow.spike.entitlement.EntitlementService.BusinessRejectException;
import com.resolveflow.spike.entitlement.EntitlementService.EntitlementConflictException;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.dao.DataAccessException;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.test.context.DynamicPropertyRegistry;
import org.springframework.test.context.DynamicPropertySource;
import org.testcontainers.containers.MySQLContainer;
import org.testcontainers.junit.jupiter.Container;
import org.testcontainers.junit.jupiter.Testcontainers;

import java.util.List;
import java.util.concurrent.Callable;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.Future;
import java.util.concurrent.atomic.AtomicInteger;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

/**
 * T00 gate: does the fixed stack actually run MySQL 8.4 transactions, Flyway
 * migrations and MyBatis against a real server?
 *
 * <p>These assert the invariants from docs/domain-model.md (INV-01, INV-02) rather
 * than restating the implementation: the concurrency and constraint tests must fail
 * if the conditional-UPDATE / row-lock mechanics are wrong.
 */
@SpringBootTest
@Testcontainers
class MySQLTransactionIT {

    // Tagged locally from the mirror-pulled image so the canonical name resolves.
    @Container
    static final MySQLContainer<?> MYSQL = new MySQLContainer<>("mysql:8.4")
            .withDatabaseName("spike_db")
            .withUsername("spike")
            .withPassword("spike");

    @DynamicPropertySource
    static void datasource(DynamicPropertyRegistry registry) {
        registry.add("spring.datasource.url", MYSQL::getJdbcUrl);
        registry.add("spring.datasource.username", MYSQL::getUsername);
        registry.add("spring.datasource.password", MYSQL::getPassword);
    }

    @Autowired
    JdbcTemplate jdbc;
    @Autowired
    EntitlementService service;

    static final long ORDER_ID = 9001L;
    static final long LINE_ID = 7001L;
    static final long PAID = 20_000L;   // 200.00 in minor units

    @BeforeEach
    void seed() {
        jdbc.update("DELETE FROM entitlement_operation WHERE line_id = ?", LINE_ID);
        jdbc.update("DELETE FROM line_entitlement WHERE line_id = ?", LINE_ID);
        jdbc.update("DELETE FROM payment_ledger WHERE order_id = ?", ORDER_ID);
        jdbc.update("DELETE FROM order_line WHERE id = ?", LINE_ID);
        jdbc.update("DELETE FROM orders WHERE id = ?", ORDER_ID);

        jdbc.update("INSERT INTO orders (id, merchant_id, customer_id, status) VALUES (?,1,1,'PAID')", ORDER_ID);
        jdbc.update("INSERT INTO order_line (id, order_id, sku, quantity, line_paid_amount, currency) "
                + "VALUES (?,?, 'SKU-1', 1, ?, 'CNY')", LINE_ID, ORDER_ID, PAID);
        jdbc.update("INSERT INTO payment_ledger (order_id, paid_amount, refunded_amount, reserved_refund_amount) "
                + "VALUES (?,?,0,0)", ORDER_ID, PAID);
        jdbc.update("INSERT INTO line_entitlement (line_id, merchant_id, action, operation_id, state) "
                + "VALUES (?,1,'NONE',NULL,'FREE')", LINE_ID);
    }

    @Test
    @DisplayName("Flyway applied V1 on a real MySQL 8.4 server")
    void flywayRanOnRealMySql84() {
        String version = jdbc.queryForObject("SELECT VERSION()", String.class);
        assertThat(version).as("must be the 8.4 LTS line, not 8.0").startsWith("8.4.");

        Integer applied = jdbc.queryForObject(
                "SELECT COUNT(*) FROM flyway_schema_history WHERE success = 1 AND version = '1'", Integer.class);
        assertThat(applied).isEqualTo(1);

        // The CHECK constraints exist, so the DB is a real backstop, not just app logic.
        Integer checks = jdbc.queryForObject("""
                SELECT COUNT(*) FROM information_schema.table_constraints
                 WHERE constraint_schema = DATABASE()
                   AND constraint_type = 'CHECK'
                   AND table_name IN ('payment_ledger','line_entitlement','order_line')
                """, Integer.class);
        assertThat(checks).isGreaterThanOrEqualTo(4);
    }

    @Test
    @DisplayName("Reserve occupies the line and moves reserved money")
    void reserveOccupiesLineAndReservesMoney() {
        var result = service.reserveRefund(LINE_ID, ORDER_ID, "op-1", 5_000L);

        assertThat(result.state()).isEqualTo("RESERVED");
        EntitlementRow line = service.findLine(LINE_ID).orElseThrow();
        assertThat(line.operationId()).isEqualTo("op-1");
        assertThat(line.action()).isEqualTo("REFUND");

        LedgerRow ledger = service.findLedger(ORDER_ID).orElseThrow();
        assertThat(ledger.reservedRefundAmount()).isEqualTo(5_000L);
        assertThat(ledger.refundedAmount()).isZero();
        assertWithinPaid(ledger);
    }

    @Test
    @DisplayName("Same operation retried returns the original result without double reserving")
    void sameOperationIsIdempotent() {
        service.reserveRefund(LINE_ID, ORDER_ID, "op-1", 5_000L);
        var again = service.reserveRefund(LINE_ID, ORDER_ID, "op-1", 5_000L);

        assertThat(again.state()).isEqualTo("RESERVED");
        assertThat(service.findLedger(ORDER_ID).orElseThrow().reservedRefundAmount())
                .as("a retried operation must not reserve twice")
                .isEqualTo(5_000L);
    }

    @Test
    @DisplayName("INV-02: a different operation cannot occupy an already-held line")
    void secondOperationOnHeldLineConflicts() {
        service.reserveRefund(LINE_ID, ORDER_ID, "op-1", 1_000L);

        assertThatThrownBy(() -> service.reserveRefund(LINE_ID, ORDER_ID, "op-2", 1_000L))
                .isInstanceOf(EntitlementConflictException.class);

        assertThat(service.findLine(LINE_ID).orElseThrow().operationId())
                .as("the loser must not have overwritten the holder")
                .isEqualTo("op-1");
        LedgerRow ledger = service.findLedger(ORDER_ID).orElseThrow();
        assertThat(ledger.reservedRefundAmount()).isEqualTo(1_000L);
        assertWithinPaid(ledger);
    }

    @Test
    @DisplayName("INV-01: reserving beyond the paid amount is rejected and leaves no trace")
    void reserveBeyondPaidIsRejected() {
        service.reserveRefund(LINE_ID, ORDER_ID, "op-1", PAID - 1_000L);

        assertThatThrownBy(() -> service.reserveRefund(LINE_ID, ORDER_ID, "op-2", 5_000L))
                .isInstanceOf(EntitlementConflictException.class)
                .as("op-2 is blocked by INV-02 before it can breach INV-01; both are refusals");

        // Even with the line free, the ledger gate rejects.
        jdbc.update("UPDATE line_entitlement SET state='FREE', operation_id=NULL, version=version+1 WHERE line_id=?", LINE_ID);
        assertThatThrownBy(() -> service.reserveRefund(LINE_ID, ORDER_ID, "op-3", 5_000L))
                .isInstanceOf(BusinessRejectException.class);

        LedgerRow ledger = service.findLedger(ORDER_ID).orElseThrow();
        assertThat(ledger.reservedRefundAmount()).isEqualTo(PAID - 1_000L);
        assertWithinPaid(ledger);
    }

    @Test
    @DisplayName("INV-01 is enforced by the database even when the application is bypassed")
    void databaseBlocksOversubscription() {
        jdbc.update("UPDATE payment_ledger SET reserved_refund_amount = ? WHERE order_id = ?", PAID, ORDER_ID);

        // MySQL reports a CHECK violation as SQLState HY000 / error 3819, so Spring
        // surfaces it as UncategorizedSQLException rather than DataIntegrityViolation.
        // Asserting on the constraint name keeps this about the invariant, not the mapping.
        assertThatThrownBy(() -> jdbc.update(
                "UPDATE payment_ledger SET reserved_refund_amount = reserved_refund_amount + 1 WHERE order_id = ?",
                ORDER_ID))
                .isInstanceOf(DataAccessException.class)
                .hasMessageContaining("ck_ledger_within_paid");
    }

    @Test
    @DisplayName("Concurrent reserve on one line yields exactly one winner")
    void concurrentReserveHasSingleWinner() throws Exception {
        int threads = 16;
        ExecutorService pool = Executors.newFixedThreadPool(threads);
        AtomicInteger reserved = new AtomicInteger();
        AtomicInteger conflicts = new AtomicInteger();
        AtomicInteger other = new AtomicInteger();
        try {
            List<Callable<Void>> jobs = new java.util.ArrayList<>();
            for (int i = 0; i < threads; i++) {
                final String op = "op-c" + i;
                jobs.add(() -> {
                    try {
                        service.reserveRefund(LINE_ID, ORDER_ID, op, 1_000L);
                        reserved.incrementAndGet();
                    } catch (EntitlementConflictException e) {
                        conflicts.incrementAndGet();
                    } catch (RuntimeException e) {
                        other.incrementAndGet();
                    }
                    return null;
                });
            }
            for (Future<Void> f : pool.invokeAll(jobs)) {
                f.get();
            }
        } finally {
            pool.shutdownNow();
        }

        assertThat(reserved.get()).as("exactly one operation may hold the line").isEqualTo(1);
        assertThat(conflicts.get() + other.get()).isEqualTo(threads - 1);
        LedgerRow ledger = service.findLedger(ORDER_ID).orElseThrow();
        assertThat(ledger.reservedRefundAmount())
                .as("losers must not have leaked a reservation into the ledger")
                .isEqualTo(1_000L);
        assertWithinPaid(ledger);
    }

    @Test
    @DisplayName("Full lifecycle: reserve -> start -> commit moves reserved into refunded exactly once")
    void lifecycleSettlesMoneyOnce() {
        service.reserveRefund(LINE_ID, ORDER_ID, "op-1", 5_000L);
        assertThat(service.start(LINE_ID, "op-1").state()).isEqualTo("IN_USE");
        assertThat(service.commitRefund(LINE_ID, ORDER_ID, "op-1", 5_000L).state()).isEqualTo("CONSUMED");

        LedgerRow ledger = service.findLedger(ORDER_ID).orElseThrow();
        assertThat(ledger.refundedAmount()).isEqualTo(5_000L);
        assertThat(ledger.reservedRefundAmount()).isZero();
        assertWithinPaid(ledger);

        // Committing again must not double-refund.
        assertThatThrownBy(() -> service.commitRefund(LINE_ID, ORDER_ID, "op-1", 5_000L))
                .isInstanceOf(EntitlementConflictException.class);
        assertThat(service.findLedger(ORDER_ID).orElseThrow().refundedAmount()).isEqualTo(5_000L);
    }

    @Test
    @DisplayName("IN_USE may not be started again, and a stale version cannot overwrite")
    void stateAndVersionGuardTransitions() {
        service.reserveRefund(LINE_ID, ORDER_ID, "op-1", 1_000L);
        service.start(LINE_ID, "op-1");

        assertThatThrownBy(() -> service.start(LINE_ID, "op-1"))
                .isInstanceOf(EntitlementConflictException.class);

        long version = service.findLine(LINE_ID).orElseThrow().version();
        int rows = jdbc.update("UPDATE line_entitlement SET state='FREE' WHERE line_id=? AND version=?", LINE_ID, version - 5);
        assertThat(rows).as("a stale version must affect zero rows").isZero();
    }

    private void assertWithinPaid(LedgerRow ledger) {
        assertThat(ledger.refundedAmount()).isNotNegative();
        assertThat(ledger.reservedRefundAmount()).isNotNegative();
        assertThat(ledger.refundedAmount() + ledger.reservedRefundAmount())
                .as("INV-01: refunded + reserved <= paid")
                .isLessThanOrEqualTo(ledger.paidAmount());
    }
}