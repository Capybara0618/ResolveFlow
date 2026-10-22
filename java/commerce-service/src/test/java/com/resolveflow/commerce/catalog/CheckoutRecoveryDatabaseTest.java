package com.resolveflow.commerce.catalog;

import static org.assertj.core.api.Assertions.*;
import static org.mockito.ArgumentMatchers.*;
import static org.mockito.Mockito.*;

import com.resolveflow.commerce.CommerceDatabaseTest;
import com.resolveflow.shared.shopping.CheckoutWire.*;
import com.resolveflow.shared.shopping.ShoppingWire.*;
import io.micrometer.core.instrument.simple.SimpleMeterRegistry;
import java.sql.Timestamp;
import java.time.Clock;
import java.time.Instant;
import java.time.ZoneOffset;
import java.util.UUID;
import java.util.concurrent.Executors;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.test.context.bean.override.mockito.MockitoSpyBean;

class CheckoutRecoveryDatabaseTest extends CommerceDatabaseTest {
    @Autowired
    ShoppingService shop;

    @Autowired
    CheckoutPayments payments;

    @Autowired
    PurchaseReads purchases;

    @Autowired
    JdbcTemplate jdbc;

    @MockitoSpyBean
    SimulatedCheckoutProvider provider;

    private Instant now;

    @BeforeEach
    void resetProvider() {
        reset(provider);
        now = Instant.now().plusSeconds(5);
    }

    private Draft draft() {
        return shop.create(new DraftCommand(
                "M-1001", "RECOVERY-TEST", UUID.randomUUID().toString(), new DraftRequest("SKU-1001-BLACK", 1, 1L)));
    }

    private Payment unknown(boolean receipt) {
        doAnswer(i -> {
                    if (receipt) i.callRealMethod();
                    throw new SimulatedCheckoutProvider.Uncertain();
                })
                .when(provider)
                .charge(anyString(), anyLong());
        var d = draft();
        var p = payments.pay(
                d.draftId(),
                new PayCommand("M-1001", "RECOVERY-TEST", UUID.randomUUID().toString()));
        reset(provider);
        return p;
    }

    private CheckoutRecoveryService worker(Instant time) {
        return new CheckoutRecoveryService(
                jdbc, payments, provider, Clock.fixed(time, ZoneOffset.UTC), new SimpleMeterRegistry());
    }

    private void due(Payment p, Instant at) {
        jdbc.update(
                "UPDATE checkout_payment_attempt SET next_reconcile_at=? WHERE attempt_id=?",
                Timestamp.from(at),
                p.attemptId());
    }

    @Test
    void closesExpiredDraftPersistentlyAndKeepsPublicExpiredProjection() {
        var d = draft();
        jdbc.update(
                "UPDATE checkout_draft SET created_at=?,expires_at=? WHERE draft_id=?",
                Timestamp.from(now.minusSeconds(1000)),
                Timestamp.from(now.minusSeconds(1)),
                d.draftId());
        worker(now).tick(100);
        assertThat(jdbc.queryForObject("SELECT status FROM checkout_draft WHERE draft_id=?", String.class, d.draftId()))
                .isEqualTo("CANCELLED");
        assertThat(shop.read(d.draftId(), "M-1001", "RECOVERY-TEST").status()).isEqualTo("EXPIRED");
        assertThat(purchases
                        .list("M-1001", "RECOVERY-TEST", "EXPIRED", null, 48)
                        .items())
                .anyMatch(p -> d.draftId().equals(p.draftId()));
        assertThatThrownBy(() -> payments.pay(d.draftId(), new PayCommand("M-1001", "RECOVERY-TEST", "late")))
                .isInstanceOf(ShoppingService.Refused.class);
        verify(provider, never()).charge(anyString(), anyLong());
    }

    @Test
    void unknownWithoutReceiptNeverExpiresCancelsChargesOrChangesAttempt() {
        var p = unknown(false);
        jdbc.update(
                "UPDATE checkout_draft SET created_at=?,expires_at=? WHERE draft_id=?",
                Timestamp.from(now.minusSeconds(1000)),
                Timestamp.from(now.minusSeconds(1)),
                p.draftId());
        worker(now).tick(100);
        assertThat(payments.snapshot(p.draftId(), "M-1001", "RECOVERY-TEST").attemptId())
                .isEqualTo(p.attemptId());
        assertThat(shop.read(p.draftId(), "M-1001", "RECOVERY-TEST").status()).isEqualTo("PAYMENT_PENDING");
        assertThat(jdbc.queryForObject(
                        "SELECT reconcile_count FROM checkout_payment_attempt WHERE attempt_id=?",
                        Integer.class,
                        p.attemptId()))
                .isEqualTo(1);
        assertThatThrownBy(() -> payments.cancel(p.draftId(), new ScopeCommand("M-1001", "RECOVERY-TEST")))
                .isInstanceOf(ShoppingService.Refused.class);
        verify(provider, never()).charge(anyString(), anyLong());
    }

    @Test
    void receiptAfterLostResponsePublishesOriginalAttemptExactlyOnce() {
        var p = unknown(true);
        worker(now).tick(100);
        worker(now.plusSeconds(31)).tick(100);
        var result = payments.snapshot(p.draftId(), "M-1001", "RECOVERY-TEST");
        assertThat(result.status()).isEqualTo("SUCCEEDED");
        assertThat(result.attemptId()).isEqualTo(p.attemptId());
        assertThat(jdbc.queryForObject(
                        "SELECT COUNT(*) FROM order_line WHERE order_id=?", Integer.class, result.orderId()))
                .isEqualTo(1);
        assertThat(jdbc.queryForObject(
                        "SELECT paid_amount FROM payment_ledger WHERE order_id=?", Long.class, result.orderId()))
                .isEqualTo(p.totalAmount());
        verify(provider, never()).charge(anyString(), anyLong());
    }

    @Test
    void unresolvedHeadIsRescheduledSoNextDueReceiptIsNotStarved() {
        var first = unknown(false);
        var next = unknown(true);
        due(first, now.minusSeconds(172800));
        due(next, now.minusSeconds(86400));
        worker(now).tick(1);
        worker(now).tick(1);
        assertThat(payments.snapshot(next.draftId(), "M-1001", "RECOVERY-TEST").status())
                .isEqualTo("SUCCEEDED");
        assertThat(payments.snapshot(first.draftId(), "M-1001", "RECOVERY-TEST").status())
                .isEqualTo("UNKNOWN");
        verify(provider, never()).charge(anyString(), anyLong());
    }

    @Test
    void failedPublicationRollsBackAndLaterWorkerReusesOriginalIds() {
        var p = unknown(true);
        String order = jdbc.queryForObject(
                "SELECT order_id FROM checkout_payment_attempt WHERE attempt_id=?", String.class, p.attemptId());
        jdbc.update(
                "INSERT INTO orders(order_id,merchant_id,customer_id,order_status,currency,paid_at,created_at) VALUES(?,'M-1001','RECOVERY-TEST','PAID','CNY',?,?)",
                order,
                Timestamp.from(now),
                Timestamp.from(now));
        worker(now).tick(100);
        assertThat(payments.snapshot(p.draftId(), "M-1001", "RECOVERY-TEST").status())
                .isEqualTo("UNKNOWN");
        assertThat(jdbc.queryForObject("SELECT COUNT(*) FROM order_line WHERE order_id=?", Integer.class, order))
                .isZero();
        jdbc.update("DELETE FROM orders WHERE order_id=?", order);
        worker(now.plusSeconds(31)).tick(100);
        assertThat(payments.snapshot(p.draftId(), "M-1001", "RECOVERY-TEST").orderId())
                .isEqualTo(order);
        verify(provider, never()).charge(anyString(), anyLong());
    }

    @Test
    void lookupFailureDoesNotBlockAnotherReceiptAndProviderRunsOutsideTransactions() {
        var first = unknown(false);
        var next = unknown(true);
        doAnswer(i -> {
                    assertThat(org.springframework.transaction.support.TransactionSynchronizationManager
                                    .isActualTransactionActive())
                            .isFalse();
                    if (first.attemptId().equals(i.getArgument(0)))
                        throw new IllegalStateException("synthetic lookup failure");
                    return i.callRealMethod();
                })
                .when(provider)
                .lookup(anyString());
        worker(now).tick(100);
        assertThat(payments.snapshot(first.draftId(), "M-1001", "RECOVERY-TEST").status())
                .isEqualTo("UNKNOWN");
        assertThat(payments.snapshot(next.draftId(), "M-1001", "RECOVERY-TEST").status())
                .isEqualTo("SUCCEEDED");
        assertThat(jdbc.queryForObject(
                        "SELECT last_reconcile_error FROM checkout_payment_attempt WHERE attempt_id=?",
                        String.class,
                        first.attemptId()))
                .isEqualTo("LOOKUP_OR_PUBLICATION_FAILED");
        verify(provider, never()).charge(anyString(), anyLong());
    }

    @Test
    void competingWorkersClaimOneOriginalAttempt() throws Exception {
        var p = unknown(true);
        try (var pool = Executors.newFixedThreadPool(2)) {
            var a = pool.submit(() -> worker(now).tick(100));
            var b = pool.submit(() -> worker(now).tick(100));
            a.get();
            b.get();
        }
        assertThat(jdbc.queryForObject(
                        "SELECT reconcile_count FROM checkout_payment_attempt WHERE attempt_id=?",
                        Integer.class,
                        p.attemptId()))
                .isEqualTo(1);
        assertThat(payments.snapshot(p.draftId(), "M-1001", "RECOVERY-TEST").status())
                .isEqualTo("SUCCEEDED");
        verify(provider, never()).charge(anyString(), anyLong());
    }
}
