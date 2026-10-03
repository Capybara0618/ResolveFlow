package com.resolveflow.commerce.catalog;

import static org.assertj.core.api.Assertions.*;
import static org.mockito.Mockito.*;

import com.resolveflow.commerce.CommerceDatabaseTest;
import com.resolveflow.shared.shopping.CheckoutWire.PayCommand;
import com.resolveflow.shared.shopping.FulfillmentWire.ShipCommand;
import com.resolveflow.shared.shopping.ShoppingWire.DraftCommand;
import com.resolveflow.shared.shopping.ShoppingWire.DraftRequest;
import java.util.UUID;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.test.context.bean.override.mockito.MockitoSpyBean;

class FulfillmentDatabaseTest extends CommerceDatabaseTest {
    @Autowired
    ShoppingService shop;

    @Autowired
    CheckoutPayments payments;

    @Autowired
    MerchantTradeService trades;

    @Autowired
    CartService cart;

    @Autowired
    MultiCheckoutService multi;

    @Autowired
    org.springframework.transaction.support.TransactionTemplate tx;

    @MockitoSpyBean
    JdbcTemplate jdbc;

    private static String key() {
        return UUID.randomUUID().toString();
    }

    private String paid() {
        var draft = shop.create(
                new DraftCommand("M-1001", "FULFILLMENT-TEST", key(), new DraftRequest("SKU-1001-BLACK", 1, 1L)));
        return payments.pay(draft.draftId(), new PayCommand("M-1001", "FULFILLMENT-TEST", key()))
                .orderId();
    }

    private String multiPaid() {
        String buyer = "FULFILLMENT-MULTI-" + key();
        for (var sku : java.util.List.of("SKU-1001-BLACK", "SKU-1002-WHITE")) {
            long revision = cart.read("M-1001", buyer).revision();
            cart.write(new com.resolveflow.shared.shopping.CartWire.Command(
                    "M-1001",
                    buyer,
                    key(),
                    new com.resolveflow.shared.shopping.CartWire.Request(sku, 1, revision, 1L)));
        }
        var q = multi.quote(new com.resolveflow.shared.shopping.MultiCheckoutWire.QuoteCommand(
                "M-1001",
                buyer,
                new com.resolveflow.shared.shopping.MultiCheckoutWire.QuoteRequest(
                        2L, java.util.List.of("SKU-1001-BLACK", "SKU-1002-WHITE"))));
        var d = multi.create(new com.resolveflow.shared.shopping.MultiCheckoutWire.Command(
                "M-1001",
                buyer,
                key(),
                new com.resolveflow.shared.shopping.MultiCheckoutWire.Request(
                        2L,
                        q.lines().stream()
                                .map(l -> new DraftRequest(l.skuId(), l.quantity(), l.skuVersion()))
                                .toList())));
        return payments.pay(d.draftId(), new PayCommand("M-1001", buyer, key())).orderId();
    }

    @Test
    void paidFactIsUnshippedAndFirstShipmentHasImmutableReplay() {
        String id = paid();
        var before = trades.read(id, "M-1001");
        assertThat(before.fulfillment().status()).isEqualTo("NOT_SHIPPED");
        assertThat(before.canShip()).isTrue();
        assertThat(before.lineAftercare()).hasSize(1).allSatisfy(line -> {
            assertThat(line.state()).isEqualTo("FREE");
            assertThat(line.refundedAmount()).isZero();
            assertThat(line.reservedAmount()).isZero();
        });
        assertThat(before.fulfillment().lines().getFirst().events().getFirst().code())
                .isEqualTo("ORDER_PAID");
        var command = new ShipCommand("M-1001", "admin-test", key(), 1L);
        var result = trades.ship(id, command);
        assertThat(result.status()).isEqualTo("IN_TRANSIT");
        assertThat(result.version()).isEqualTo(2L);
        assertThat(result.lines().getFirst().events()).hasSize(2);
        assertThat(trades.ship(id, command)).isEqualTo(result);
        assertThatThrownBy(() -> trades.ship(id, new ShipCommand("M-1001", "admin-test", key(), 2L)))
                .isInstanceOf(ShoppingService.Refused.class);
        assertThatThrownBy(() -> trades.ship(id, new ShipCommand("M-1001", "another", command.idempotencyKey(), 1L)))
                .isInstanceOf(ShoppingService.Refused.class);
    }

    @Test
    void multiLineAftercareDoesNotAssignOneLinesReservationToAnotherLine() {
        String id = multiPaid();
        var original = trades.read(id, "M-1001").lineAftercare();
        assertThat(original).hasSize(2);
        String target = original.getFirst().lineId();
        jdbc.update(
                "UPDATE line_refund SET state='RESERVED',operation_id=?,version=version+1 WHERE line_id=?",
                key(),
                target);
        var facts = trades.read(id, "M-1001").lineAftercare();
        assertThat(facts)
                .filteredOn(f -> f.lineId().equals(target))
                .singleElement()
                .satisfies(f -> {
                    assertThat(f.state()).isEqualTo("RESERVED");
                    assertThat(f.reservedAmount()).isPositive();
                    assertThat(f.refundedAmount()).isZero();
                });
        assertThat(facts)
                .filteredOn(f -> !f.lineId().equals(target))
                .singleElement()
                .satisfies(f -> {
                    assertThat(f.state()).isEqualTo("FREE");
                    assertThat(f.reservedAmount()).isZero();
                });
        jdbc.update("DELETE FROM line_refund WHERE line_id=?", target);
        assertThat(trades.read(id, "M-1001").lineAftercare())
                .filteredOn(f -> f.lineId().equals(target))
                .singleElement()
                .satisfies(f -> {
                    assertThat(f.state()).isEqualTo("MISSING");
                    assertThat(f.reservedAmount()).isNull();
                });
    }

    @Test
    void foreignAndLegacyOrdersCannotBeShippedAndNeverLeak() {
        String id = paid();
        assertThatThrownBy(() -> trades.read(id, "M-1002")).isInstanceOf(ShoppingService.Refused.class);
        assertThatThrownBy(() -> trades.ship(id, new ShipCommand("M-1002", "admin-test", key(), 1L)))
                .isInstanceOf(ShoppingService.Refused.class);
        assertThatThrownBy(() -> trades.buyer(id, "M-1001", "foreign")).isInstanceOf(ShoppingService.Refused.class);
        var legacy = jdbc.queryForObject("SELECT order_id FROM order_line WHERE line_id='7101'", String.class);
        assertThat(trades.read(legacy, "M-1001").canShip()).isFalse();
        assertThat(trades.read(legacy, "M-1001").fulfillment().status()).isEqualTo("DELIVERED");
    }

    @Test
    void reservationAndSuccessBothPreventShipmentAndStaleVersionDoesNotWrite() {
        String id = paid();
        assertThatThrownBy(() -> trades.ship(id, new ShipCommand("M-1001", "admin-test", key(), 2L)))
                .isInstanceOf(ShoppingService.Refused.class);
        jdbc.update("UPDATE payment_ledger SET reserved_refund_amount=32900 WHERE order_id=?", id);
        assertThat(trades.read(id, "M-1001").canShip()).isFalse();
        assertThatThrownBy(() -> trades.ship(id, new ShipCommand("M-1001", "admin-test", key(), 1L)))
                .isInstanceOf(ShoppingService.Refused.class);
        jdbc.update("UPDATE payment_ledger SET reserved_refund_amount=0,refunded_amount=32900 WHERE order_id=?", id);
        assertThatThrownBy(() -> trades.ship(id, new ShipCommand("M-1001", "admin-test", key(), 1L)))
                .isInstanceOf(ShoppingService.Refused.class);
        assertThat(trades.read(id, "M-1001").fulfillment().status()).isEqualTo("NOT_SHIPPED");
        assertThat(jdbc.queryForObject(
                        "SELECT COUNT(*) FROM shipment_event e JOIN order_line l ON l.line_id=e.line_id WHERE l.order_id=?",
                        Integer.class,
                        id))
                .isEqualTo(1);
    }

    @Test
    void multiLineSecondEventFailureRollsBackEveryShipmentAndOriginalKeyRecovers() {
        String id = multiPaid();
        var command = new ShipCommand("M-1001", "admin-test", key(), 1L);
        var counter = new java.util.concurrent.atomic.AtomicInteger();
        doAnswer(invocation -> {
                    if (counter.incrementAndGet() == 2)
                        throw new org.springframework.dao.DataIntegrityViolationException(
                                "synthetic second event failure");
                    return invocation.callRealMethod();
                })
                .when(jdbc)
                .update(
                        eq(
                                "INSERT INTO shipment_event(line_id,code,occurred_at,source_version) VALUES(?,'SIMULATED_SHIPPED',?,2)"),
                        any(Object[].class));
        try {
            assertThatThrownBy(() -> trades.ship(id, command))
                    .isInstanceOf(org.springframework.dao.DataIntegrityViolationException.class);
        } finally {
            reset(jdbc);
        }
        var original = trades.read(id, "M-1001");
        assertThat(original.canShip()).isTrue();
        assertThat(original.fulfillment().lines()).allSatisfy(l -> {
            assertThat(l.status()).isEqualTo("NOT_SHIPPED");
            assertThat(l.events()).hasSize(1);
        });
        var result = trades.ship(id, command);
        assertThat(result.lines())
                .hasSize(2)
                .allSatisfy(l -> assertThat(l.events()).hasSize(2));
        assertThat(trades.ship(id, command)).isEqualTo(result);
    }

    @Test
    void concurrentOriginalShipmentReplaysOneEventPerLine() throws Exception {
        String id = multiPaid();
        var command = new ShipCommand("M-1001", "admin-test", key(), 1L);
        try (var pool = java.util.concurrent.Executors.newFixedThreadPool(2)) {
            var a = pool.submit(() -> trades.ship(id, command));
            var b = pool.submit(() -> trades.ship(id, command));
            assertThat(a.get()).isEqualTo(b.get());
        }
        assertThat(trades.read(id, "M-1001").fulfillment().lines())
                .allSatisfy(l -> assertThat(l.events()).hasSize(2));
    }

    @Test
    void refundLedgerWinnerPreventsShipmentAfterWaitingForLock() throws Exception {
        String id = paid();
        var reserved = new java.util.concurrent.CountDownLatch(1);
        var release = new java.util.concurrent.CountDownLatch(1);
        try (var pool = java.util.concurrent.Executors.newFixedThreadPool(2)) {
            var winner = pool.submit(() -> tx.execute(s -> {
                jdbc.queryForList("SELECT order_id FROM payment_ledger WHERE order_id=? FOR UPDATE", id);
                jdbc.update("UPDATE payment_ledger SET reserved_refund_amount=32900 WHERE order_id=?", id);
                reserved.countDown();
                try {
                    if (!release.await(10, java.util.concurrent.TimeUnit.SECONDS))
                        throw new IllegalStateException("test latch timeout");
                } catch (InterruptedException e) {
                    throw new RuntimeException(e);
                }
                return true;
            }));
            assertThat(reserved.await(10, java.util.concurrent.TimeUnit.SECONDS))
                    .isTrue();
            var waiting = pool.submit(() -> trades.ship(id, new ShipCommand("M-1001", "admin-test", key(), 1L)));
            release.countDown();
            assertThat(winner.get()).isTrue();
            assertThatThrownBy(waiting::get).hasCauseInstanceOf(ShoppingService.Refused.class);
        } finally {
            release.countDown();
        }
        assertThat(trades.read(id, "M-1001").fulfillment().status()).isEqualTo("NOT_SHIPPED");
    }

    @Test
    void missingSlotAndModifiedShipmentFactCannotAuthorizeShipment() {
        String id = paid();
        String line = trades.read(id, "M-1001").fulfillment().lines().getFirst().lineId();
        jdbc.update("UPDATE shipment SET source_version=2 WHERE line_id=?", line);
        assertThat(trades.read(id, "M-1001").canShip()).isFalse();
        assertThatThrownBy(() -> trades.ship(id, new ShipCommand("M-1001", "admin-test", key(), 1L)))
                .isInstanceOf(ShoppingService.Refused.class);
        jdbc.update("UPDATE shipment SET source_version=1 WHERE line_id=?", line);
        jdbc.update("DELETE FROM line_refund WHERE line_id=?", line);
        assertThat(trades.read(id, "M-1001").canShip()).isFalse();
    }

    @Test
    void keysetPageIsMerchantAndStatusBoundAndKeepsAllLines() {
        String first = multiPaid(), second = paid();
        var page = trades.list("M-1001", "NOT_SHIPPED", null, 1);
        assertThat(page.items()).hasSize(1);
        assertThat(page.nextCursor()).isNotNull();
        assertThat(trades.list("M-1001", "NOT_SHIPPED", page.nextCursor(), 1).items())
                .hasSize(1);
        assertThatThrownBy(() -> trades.list("M-1002", "NOT_SHIPPED", page.nextCursor(), 1))
                .isInstanceOf(IllegalArgumentException.class);
        assertThatThrownBy(() -> trades.list("M-1001", null, page.nextCursor(), 1))
                .isInstanceOf(IllegalArgumentException.class);
        assertThatThrownBy(() -> trades.list("M-1001", "INVALID", null, 1))
                .isInstanceOf(IllegalArgumentException.class);
        assertThatThrownBy(() -> trades.list("M-1001", null, null, 49)).isInstanceOf(IllegalArgumentException.class);
        assertThat(trades.read(first, "M-1001").purchase().lines()).hasSize(2);
        assertThat(trades.buyer(second, "M-1001", "FULFILLMENT-TEST").synthetic())
                .isTrue();
    }
}
