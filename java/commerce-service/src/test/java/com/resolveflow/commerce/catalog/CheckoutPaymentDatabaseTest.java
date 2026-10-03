package com.resolveflow.commerce.catalog;

import static org.assertj.core.api.Assertions.*;
import static org.mockito.Mockito.*;

import com.resolveflow.commerce.CommerceDatabaseTest;
import com.resolveflow.shared.shopping.CheckoutWire.*;
import com.resolveflow.shared.shopping.ShoppingWire.*;
import java.sql.Timestamp;
import java.time.Instant;
import java.util.UUID;
import java.util.concurrent.Executors;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.test.context.bean.override.mockito.MockitoSpyBean;

class CheckoutPaymentDatabaseTest extends CommerceDatabaseTest {
    @Autowired
    ShoppingService shop;

    @Autowired
    CheckoutPayments payments;

    @Autowired
    JdbcTemplate jdbc;

    @Autowired
    PurchaseReads purchases;

    @MockitoSpyBean
    SimulatedCheckoutProvider provider;

    private static final String MERCHANT = "M-1001", CUSTOMER = "TEST-CHECKOUT";

    @AfterEach
    void resetProvider() {
        reset(provider);
        // Only this class's fixture scope in the disposable test container, never demo data.
        var ids = jdbc.queryForList(
                "SELECT draft_id FROM checkout_draft WHERE merchant_id=? AND customer_id=?",
                String.class,
                MERCHANT,
                CUSTOMER);
        var orders = jdbc.queryForList(
                "SELECT order_id FROM orders WHERE merchant_id=? AND customer_id=?", String.class, MERCHANT, CUSTOMER);
        for (var id : ids) {
            jdbc.update(
                    "DELETE FROM simulated_checkout_receipt WHERE attempt_id IN (SELECT attempt_id FROM checkout_payment_attempt WHERE draft_id=?)",
                    id);
            jdbc.update("DELETE FROM checkout_payment_attempt WHERE draft_id=?", id);
            jdbc.update("DELETE FROM checkout_draft WHERE draft_id=?", id);
        }
        for (var id : orders) {
            jdbc.update(
                    "DELETE FROM shipment_event WHERE line_id IN (SELECT line_id FROM order_line WHERE order_id=?)",
                    id);
            jdbc.update("DELETE FROM shipment WHERE line_id IN (SELECT line_id FROM order_line WHERE order_id=?)", id);
            jdbc.update("DELETE FROM order_fulfillment WHERE order_id=?", id);
            jdbc.update(
                    "DELETE FROM line_refund WHERE line_id IN (SELECT line_id FROM order_line WHERE order_id=?)", id);
            jdbc.update("DELETE FROM order_line WHERE order_id=?", id);
            jdbc.update("DELETE FROM payment_ledger WHERE order_id=?", id);
            jdbc.update("DELETE FROM orders WHERE order_id=?", id);
        }
    }

    private Draft draft() {
        return shop.create(new DraftCommand(
                MERCHANT, CUSTOMER, UUID.randomUUID().toString(), new DraftRequest("SKU-1001-BLACK", 2, 1L)));
    }

    private PayCommand pay(String key) {
        return new PayCommand(MERCHANT, CUSTOMER, key);
    }

    private ScopeCommand scope() {
        return new ScopeCommand(MERCHANT, CUSTOMER);
    }

    private void expire(Draft d) {
        jdbc.update(
                "UPDATE checkout_draft SET created_at=?,expires_at=? WHERE draft_id=?",
                Timestamp.from(Instant.now().minusSeconds(1800)),
                Timestamp.from(Instant.now().minusSeconds(900)),
                d.draftId());
    }

    private int published(String id) {
        return jdbc.queryForObject(
                "SELECT COUNT(*) FROM checkout_draft WHERE draft_id=? AND order_id IS NOT NULL", Integer.class, id);
    }

    @Test
    void successPublishesOnceWithOriginalSnapshotAndSameSuccessfulReceiptTime() {
        var d = draft();
        var cmd = pay(UUID.randomUUID().toString());
        doAnswer(inv -> {
                    assertThat(org.springframework.transaction.support.TransactionSynchronizationManager
                                    .isActualTransactionActive())
                            .isFalse();
                    return inv.callRealMethod();
                })
                .when(provider)
                .charge(anyString(), anyLong());
        var p = payments.pay(d.draftId(), cmd);
        assertThat(p.status()).isEqualTo("SUCCEEDED");
        assertThat(p.totalAmount()).isEqualTo(65800);
        assertThat(payments.pay(d.draftId(), cmd)).isEqualTo(p);
        assertThat(payments.inspect(d.draftId(), MERCHANT, CUSTOMER)).isEqualTo(p);
        assertThat(shop.read(d.draftId(), MERCHANT, CUSTOMER).status()).isEqualTo("PAID");
        assertThat(jdbc.queryForMap(
                        "SELECT paid_amount,refunded_amount,reserved_refund_amount,version FROM payment_ledger WHERE order_id=?",
                        p.orderId()))
                .containsEntry("paid_amount", 65800L)
                .containsEntry("refunded_amount", 0L)
                .containsEntry("reserved_refund_amount", 0L)
                .containsEntry("version", 1L);
        var line = jdbc.queryForMap(
                "SELECT quantity,line_paid_amount,product_name,variant_text,paid_at,order_status FROM order_line WHERE line_id=?",
                p.lineId());
        assertThat(line)
                .containsEntry("quantity", 2)
                .containsEntry("line_paid_amount", 65800L)
                .containsEntry("product_name", "无线降噪耳机")
                .containsEntry("variant_text", "黑色")
                .containsEntry("order_status", "PAID");
        assertThat(jdbc.queryForObject("SELECT state FROM line_refund WHERE line_id=?", String.class, p.lineId()))
                .isEqualTo("FREE");
        assertThat(jdbc.queryForMap(
                        "SELECT status,carrier_conclusion,source_version FROM shipment WHERE line_id=?", p.lineId()))
                .containsEntry("status", "NOT_SHIPPED")
                .containsEntry("carrier_conclusion", "UNKNOWN")
                .containsEntry("source_version", 1L);
        assertThat(jdbc.queryForObject("SELECT code FROM shipment_event WHERE line_id=?", String.class, p.lineId()))
                .isEqualTo("ORDER_PAID");
        assertThat(jdbc.queryForObject("SELECT paid_at FROM orders WHERE order_id=?", Timestamp.class, p.orderId())
                        .toInstant())
                .isEqualTo(p.paidAt());
        assertThatThrownBy(() -> payments.pay(d.draftId(), pay("another-key")))
                .isInstanceOf(ShoppingService.Refused.class);
        assertThatThrownBy(() -> payments.cancel(d.draftId(), scope())).isInstanceOf(ShoppingService.Refused.class);
        assertThat(published(d.draftId())).isOne();
    }

    @Test
    void cancellationIsIdempotentAndCannotPublish() {
        var d = draft();
        assertThat(payments.cancel(d.draftId(), scope()).status()).isEqualTo("CANCELLED");
        assertThat(payments.cancel(d.draftId(), scope()).status()).isEqualTo("CANCELLED");
        assertThatThrownBy(() -> payments.pay(d.draftId(), pay("cancelled")))
                .isInstanceOf(ShoppingService.Refused.class);
        assertThat(published(d.draftId())).isZero();
        verify(provider, never()).charge(anyString(), anyLong());
    }

    @Test
    void expiredDraftCannotPayOrCancelAndHasNoAttempt() {
        var d = draft();
        expire(d);
        assertThatThrownBy(() -> payments.pay(d.draftId(), pay("expired"))).isInstanceOf(ShoppingService.Refused.class);
        assertThatThrownBy(() -> payments.cancel(d.draftId(), scope())).isInstanceOf(ShoppingService.Refused.class);
        assertThat(payments.inspect(d.draftId(), MERCHANT, CUSTOMER)).isNull();
        assertThat(published(d.draftId())).isZero();
    }

    @Test
    void unknownBeforeProviderNeverCancelsExpiresOrCreatesAnotherAttempt() {
        var d = draft();
        var cmd = pay("original");
        doThrow(new SimulatedCheckoutProvider.Uncertain()).when(provider).charge(anyString(), anyLong());
        var p = payments.pay(d.draftId(), cmd);
        assertThat(p.status()).isEqualTo("UNKNOWN");
        expire(d);
        assertThat(payments.inspect(d.draftId(), MERCHANT, CUSTOMER).attemptId())
                .isEqualTo(p.attemptId());
        assertThat(shop.read(d.draftId(), MERCHANT, CUSTOMER).status()).isEqualTo("PAYMENT_PENDING");
        assertThatThrownBy(() -> payments.cancel(d.draftId(), scope())).isInstanceOf(ShoppingService.Refused.class);
        assertThatThrownBy(() -> payments.pay(d.draftId(), pay("new-key"))).isInstanceOf(ShoppingService.Refused.class);
        assertThat(published(d.draftId())).isZero();
        reset(provider);
        var recovered = payments.pay(d.draftId(), cmd);
        assertThat(recovered.status()).isEqualTo("SUCCEEDED");
        assertThat(recovered.attemptId()).isEqualTo(p.attemptId());
    }

    @Test
    void lostResponseAfterDurableReceiptRecoversThroughLookupWithoutAnotherCharge() {
        var d = draft();
        doAnswer(inv -> {
                    inv.callRealMethod();
                    throw new SimulatedCheckoutProvider.Uncertain();
                })
                .when(provider)
                .charge(anyString(), anyLong());
        var p = payments.pay(d.draftId(), pay("lost-receipt"));
        assertThat(p.status()).isEqualTo("UNKNOWN");
        assertThat(published(d.draftId())).isZero();
        var recovered = payments.inspect(d.draftId(), MERCHANT, CUSTOMER);
        assertThat(recovered.status()).isEqualTo("SUCCEEDED");
        assertThat(recovered.attemptId()).isEqualTo(p.attemptId());
        verify(provider, times(1)).charge(anyString(), anyLong());
        assertThat(published(d.draftId())).isOne();
    }

    @Test
    void definiteFailureAllowsExplicitNewAttemptButOldKeyStillReplaysFailure() {
        var d = draft();
        doThrow(new SimulatedCheckoutProvider.Uncertain()).when(provider).charge(anyString(), anyLong());
        var failed = payments.pay(d.draftId(), pay("first"));
        jdbc.update(
                "INSERT INTO simulated_checkout_receipt(attempt_id,total_amount,status,finished_at) VALUES(?,?,'FAILED',?)",
                failed.attemptId(),
                failed.totalAmount(),
                Timestamp.from(Instant.now()));
        assertThat(payments.inspect(d.draftId(), MERCHANT, CUSTOMER).status()).isEqualTo("FAILED");
        assertThat(published(d.draftId())).isZero();
        assertThat(shop.read(d.draftId(), MERCHANT, CUSTOMER).status()).isEqualTo("WAITING_PAYMENT");
        reset(provider);
        var next = payments.pay(d.draftId(), pay("second"));
        assertThat(next.status()).isEqualTo("SUCCEEDED");
        assertThat(next.attemptId()).isNotEqualTo(failed.attemptId());
        assertThat(payments.pay(d.draftId(), pay("first")).status()).isEqualTo("FAILED");
        assertThat(published(d.draftId())).isOne();
    }

    @Test
    void failedReceiptAfterExpiryDoesNotAllowAnotherAttempt() {
        var d = draft();
        doThrow(new SimulatedCheckoutProvider.Uncertain()).when(provider).charge(anyString(), anyLong());
        var p = payments.pay(d.draftId(), pay("late-failure"));
        expire(d);
        jdbc.update(
                "INSERT INTO simulated_checkout_receipt(attempt_id,total_amount,status,finished_at) VALUES(?,?,'FAILED',?)",
                p.attemptId(),
                p.totalAmount(),
                Timestamp.from(Instant.now()));
        assertThat(payments.inspect(d.draftId(), MERCHANT, CUSTOMER).status()).isEqualTo("FAILED");
        assertThat(shop.read(d.draftId(), MERCHANT, CUSTOMER).status()).isEqualTo("EXPIRED");
        assertThatThrownBy(() -> payments.pay(d.draftId(), pay("new-late")))
                .isInstanceOf(ShoppingService.Refused.class);
        assertThat(published(d.draftId())).isZero();
    }

    @Test
    void receiptAmountConflictKeepsUnknownWithoutPublication() {
        var d = draft();
        doThrow(new SimulatedCheckoutProvider.Uncertain()).when(provider).charge(anyString(), anyLong());
        var p = payments.pay(d.draftId(), pay("amount-conflict"));
        jdbc.update(
                "INSERT INTO simulated_checkout_receipt(attempt_id,total_amount,status,finished_at) VALUES(?,1,'SUCCEEDED',?)",
                p.attemptId(),
                Timestamp.from(Instant.now()));
        assertThatThrownBy(() -> payments.inspect(d.draftId(), MERCHANT, CUSTOMER))
                .isInstanceOf(ShoppingService.Refused.class);
        assertThat(shop.read(d.draftId(), MERCHANT, CUSTOMER).status()).isEqualTo("PAYMENT_PENDING");
        assertThat(published(d.draftId())).isZero();
    }

    @Test
    void personalPurchasesMergePaidAndUnpaidWithoutDuplicatingPublishedOrders() {
        var paid = draft();
        var unpaid = draft();
        var payment = payments.pay(paid.draftId(), pay("list-payment"));
        var page = purchases.list(MERCHANT, CUSTOMER, null, null, 1);
        assertThat(page.items()).hasSize(1);
        assertThat(page.nextCursor()).isNotNull();
        var second = purchases.list(MERCHANT, CUSTOMER, null, page.nextCursor(), 1);
        assertThat(second.items()).hasSize(1);
        assertThat(second.nextCursor()).isNull();
        assertThat(java.util.List.of(
                        page.items().getFirst().purchaseId(),
                        second.items().getFirst().purchaseId()))
                .containsExactlyInAnyOrder("draft:" + paid.draftId(), "draft:" + unpaid.draftId());
        var detail = purchases.read("draft:" + paid.draftId(), MERCHANT, CUSTOMER);
        assertThat(detail.orderId()).isEqualTo(payment.orderId());
        assertThat(detail.lines().getFirst().lineId()).isEqualTo(payment.lineId());
        assertThat(purchases.list(MERCHANT, CUSTOMER, "PAID", null, 24).items()).hasSize(1);
        assertThatThrownBy(() -> purchases.read("order:" + payment.orderId(), MERCHANT, CUSTOMER))
                .isInstanceOf(ShoppingService.Refused.class);
        assertThatThrownBy(() -> purchases.read("draft:" + paid.draftId(), MERCHANT, "OTHER"))
                .isInstanceOf(ShoppingService.Refused.class);
        var legacy = purchases.read("order:00000000-0000-4000-8000-000000003001", MERCHANT, "C-B3001-M1001");
        assertThat(legacy.draftId()).isNull();
        assertThat(legacy.payment()).isNull();
        assertThat(legacy.lines().getFirst().unitAmount()).isNull();
        assertThat(legacy.lines().getFirst().assetKey()).isNull();
        assertThat(legacy.totalAmount()).isEqualTo(32900);
    }

    @Test
    void paymentAmountDoesNotFollowLaterCatalogPriceOrListingChanges() {
        var d = draft();
        try {
            jdbc.update("UPDATE catalog_sku SET unit_amount=1,listed=FALSE,version=2 WHERE sku_id='SKU-1001-BLACK'");
            assertThat(payments.pay(d.draftId(), pay("frozen")).totalAmount()).isEqualTo(65800);
        } finally {
            jdbc.update("UPDATE catalog_sku SET unit_amount=32900,listed=TRUE,version=1 WHERE sku_id='SKU-1001-BLACK'");
        }
    }

    @Test
    void twoPaymentRequestsWithSameKeyPublishOneAttemptOrderAndReceipt() throws Exception {
        var d = draft();
        var cmd = pay("parallel");
        try (var pool = Executors.newFixedThreadPool(2)) {
            var a = pool.submit(() -> payments.pay(d.draftId(), cmd));
            var b = pool.submit(() -> payments.pay(d.draftId(), cmd));
            assertThat(a.get().attemptId()).isEqualTo(b.get().attemptId());
        }
        assertThat(jdbc.queryForObject(
                        "SELECT COUNT(*) FROM checkout_payment_attempt WHERE draft_id=?", Integer.class, d.draftId()))
                .isOne();
        assertThat(published(d.draftId())).isOne();
    }

    @Test
    void cancelAndPayRaceHasExactlyOneWinner() throws Exception {
        var d = draft();
        try (var pool = Executors.newFixedThreadPool(2)) {
            var a = pool.submit(() -> {
                try {
                    return payments.pay(d.draftId(), pay("race")).status();
                } catch (ShoppingService.Refused e) {
                    return "REFUSED";
                }
            });
            var b = pool.submit(() -> {
                try {
                    return payments.cancel(d.draftId(), scope()).status();
                } catch (ShoppingService.Refused e) {
                    return "REFUSED";
                }
            });
            assertThat(java.util.List.of(a.get(), b.get())).contains("REFUSED");
        }
        var state = shop.read(d.draftId(), MERCHANT, CUSTOMER).status();
        assertThat(state).isIn("PAID", "CANCELLED");
        assertThat(published(d.draftId())).isEqualTo(state.equals("PAID") ? 1 : 0);
    }

    @Test
    void wrongCompositeScopeDoesNotTouchProviderOrRevealAttempts() {
        var d = draft();
        for (var s : java.util.List.of(new ScopeCommand(MERCHANT, "OTHER"), new ScopeCommand("M-1002", CUSTOMER))) {
            assertThatThrownBy(
                            () -> payments.pay(d.draftId(), new PayCommand(s.merchantId(), s.customerId(), "foreign")))
                    .isInstanceOf(ShoppingService.Refused.class);
            assertThatThrownBy(() -> payments.cancel(d.draftId(), s)).isInstanceOf(ShoppingService.Refused.class);
            assertThatThrownBy(() -> payments.inspect(d.draftId(), s.merchantId(), s.customerId()))
                    .isInstanceOf(ShoppingService.Refused.class);
        }
        verify(provider, never()).charge(anyString(), anyLong());
    }

    @Test
    void publicationFailureRollsBackAllBusinessRecordsAndReusesOriginalAttempt() {
        var d = draft();
        doThrow(new SimulatedCheckoutProvider.Uncertain()).when(provider).charge(anyString(), anyLong());
        var p = payments.pay(d.draftId(), pay("rollback"));
        var order = jdbc.queryForObject(
                "SELECT order_id FROM checkout_payment_attempt WHERE attempt_id=?", String.class, p.attemptId());
        var line = jdbc.queryForObject(
                "SELECT line_id FROM checkout_payment_attempt WHERE attempt_id=?", String.class, p.attemptId());
        // A scoped fixture deliberately occupies the line PK so publication fails after INSERT orders.
        jdbc.update(
                "INSERT INTO orders(order_id,merchant_id,customer_id,order_status,currency,paid_at) VALUES(?,'M-1001','CONFLICT','PAID','CNY',UTC_TIMESTAMP(6))",
                UUID.randomUUID().toString());
        var conflictOrder = jdbc.queryForObject(
                "SELECT order_id FROM orders WHERE customer_id='CONFLICT' ORDER BY created_at DESC LIMIT 1",
                String.class);
        jdbc.update(
                "INSERT INTO order_line(line_id,order_id,merchant_id,customer_id,sku,category,quantity,line_paid_amount,currency,paid_at,order_status,version) VALUES(?,?,'M-1001','CONFLICT','TEST','test',1,1,'CNY',UTC_TIMESTAMP(6),'PAID',1)",
                line,
                conflictOrder);
        reset(provider);
        provider.charge(p.attemptId(), p.totalAmount());
        try {
            assertThatThrownBy(() -> payments.inspect(d.draftId(), MERCHANT, CUSTOMER))
                    .isInstanceOf(org.springframework.dao.DataIntegrityViolationException.class);
            assertThat(jdbc.queryForObject("SELECT COUNT(*) FROM orders WHERE order_id=?", Integer.class, order))
                    .isZero();
            assertThat(jdbc.queryForObject(
                            "SELECT COUNT(*) FROM payment_ledger WHERE order_id=?", Integer.class, order))
                    .isZero();
            assertThat(published(d.draftId())).isZero();
        } finally {
            jdbc.update("DELETE FROM order_line WHERE line_id=?", line);
            jdbc.update("DELETE FROM orders WHERE order_id=?", conflictOrder);
        }
        assertThat(payments.inspect(d.draftId(), MERCHANT, CUSTOMER).status()).isEqualTo("SUCCEEDED");
        assertThat(published(d.draftId())).isOne();
    }
}
