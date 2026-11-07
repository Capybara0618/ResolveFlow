package com.resolveflow.commerce.catalog;

import static org.assertj.core.api.Assertions.*;
import static org.mockito.Mockito.*;

import com.resolveflow.commerce.CommerceDatabaseTest;
import com.resolveflow.shared.shopping.CheckoutWire.*;
import com.resolveflow.shared.shopping.CheckoutWire.Line;
import com.resolveflow.shared.shopping.MultiCheckoutWire.*;
import com.resolveflow.shared.shopping.ShoppingWire.DraftRequest;
import java.util.List;
import java.util.UUID;
import java.util.concurrent.Executors;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.test.context.bean.override.mockito.MockitoSpyBean;

class MultiCheckoutDatabaseTest extends CommerceDatabaseTest {
    private static final String BUYER = "MULTI-CHECKOUT-TEST", STORE = "M-1001";

    @Autowired
    CartService cart;

    @Autowired
    MultiCheckoutService multi;

    @Autowired
    CheckoutPayments payments;

    @Autowired
    PurchaseReads purchases;

    @Autowired
    ShoppingService shop;

    @MockitoSpyBean
    JdbcTemplate jdbc;

    @MockitoSpyBean
    SimulatedCheckoutProvider provider;

    private static String key() {
        return UUID.randomUUID().toString();
    }

    private void add(String store, String sku, int qty, long revision) {
        cart.write(new com.resolveflow.shared.shopping.CartWire.Command(
                store, BUYER, key(), new com.resolveflow.shared.shopping.CartWire.Request(sku, qty, revision, 1L)));
    }

    private Quote quote() {
        return multi.quote(
                new QuoteCommand(STORE, BUYER, new QuoteRequest(2L, List.of("SKU-1002-WHITE", "SKU-1001-BLACK"))));
    }

    private Command command(Quote q) {
        return new Command(
                q.storeId(),
                BUYER,
                key(),
                new Request(
                        q.revision(),
                        q.lines().stream()
                                .map(l -> new DraftRequest(l.skuId(), l.quantity(), l.skuVersion()))
                                .toList()));
    }

    private Command setup() {
        add(STORE, "SKU-1001-BLACK", 1, 0);
        add(STORE, "SKU-1002-WHITE", 2, 1);
        return command(quote());
    }

    private PayCommand pay() {
        return new PayCommand(STORE, BUYER, key());
    }

    private int count(String table) {
        return jdbc.queryForObject("SELECT COUNT(*) FROM " + table, Integer.class);
    }

    @Test
    void refundSummaryIsIndependentOfPaymentAndDoesNotHideOtherLines() {
        var d = multi.create(setup());
        var p = payments.pay(d.draftId(), pay());
        assertThat(purchases.read(d.purchaseId(), STORE, BUYER).refundStatus()).isEqualTo("NONE");
        for (var sample : List.of(
                new Object[] {0L, 32900L, "IN_PROGRESS"},
                new Object[] {32900L, 0L, "PARTIALLY_REFUNDED"},
                new Object[] {32900L, 39800L, "IN_PROGRESS"},
                new Object[] {72700L, 0L, "REFUNDED"})) {
            jdbc.update(
                    "UPDATE payment_ledger SET refunded_amount=?,reserved_refund_amount=? WHERE order_id=?",
                    sample[0],
                    sample[1],
                    p.orderId());
            var result = purchases.read(d.purchaseId(), STORE, BUYER);
            assertThat(result.status()).isEqualTo("PAID");
            assertThat(result.refundStatus()).isEqualTo(sample[2]);
            assertThat(result.lines()).hasSize(2);
        }
    }

    @AfterEach
    void cleanup() {
        reset(provider);
        reset(jdbc);
        for (var id : jdbc.queryForList("SELECT draft_id FROM checkout_draft WHERE buyer_id=?", String.class, BUYER)) {
            jdbc.update(
                    "DELETE FROM simulated_checkout_receipt WHERE attempt_id IN (SELECT attempt_id FROM checkout_payment_attempt WHERE draft_id=?)",
                    id);
            jdbc.update(
                    "DELETE FROM checkout_payment_line WHERE attempt_id IN (SELECT attempt_id FROM checkout_payment_attempt WHERE draft_id=?)",
                    id);
            jdbc.update("DELETE FROM checkout_payment_attempt WHERE draft_id=?", id);
            jdbc.update("DELETE FROM checkout_draft_line WHERE draft_id=?", id);
            jdbc.update("DELETE FROM checkout_draft WHERE draft_id=?", id);
        }
        for (var id : jdbc.queryForList("SELECT order_id FROM orders WHERE buyer_id=?", String.class, BUYER)) {
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
        jdbc.update("DELETE FROM shopping_cart_item WHERE buyer_id=?", BUYER);
        jdbc.update("DELETE FROM shopping_cart_request WHERE buyer_id=?", BUYER);
        jdbc.update("DELETE FROM shopping_cart WHERE buyer_id=?", BUYER);
        jdbc.update("UPDATE catalog_sku SET unit_amount=32900,version=1 WHERE sku_id='SKU-1001-BLACK'");
        jdbc.update("UPDATE catalog_product SET listed=TRUE WHERE product_id='P-1001'");
    }

    @Test
    void selectedStoreRowsOnlyAndCanonicalReplayNeverDeleteReaddedRows() {
        setup();
        add(STORE, "SKU-1003-GRAY", 1, 2);
        add("M-1002", "SKU-2001-CREAM", 1, 0);
        add("M-1002", "SKU-2002-SILVER", 1, 1);
        var q = multi.quote(
                new QuoteCommand(STORE, BUYER, new QuoteRequest(3L, List.of("SKU-1002-WHITE", "SKU-1001-BLACK"))));
        assertThat(q.totalAmount()).isEqualTo(72700);
        int orders = count("orders");
        var cmd = command(q);
        var d = multi.create(cmd);
        assertThat(d.status()).isEqualTo("WAITING_PAYMENT");
        assertThat(d.lines()).hasSize(2);
        assertThat(d.lines()).extracting(Line::lineAmount).containsExactly(32900L, 39800L);
        assertThat(cart.read(STORE, BUYER).items())
                .extracting(com.resolveflow.shared.shopping.CartWire.Item::skuId)
                .containsExactly("SKU-1003-GRAY");
        assertThat(cart.read("M-1002", BUYER).items()).hasSize(2);
        var reversed = new java.util.ArrayList<>(cmd.request().lines());
        java.util.Collections.reverse(reversed);
        assertThat(multi.create(new Command(STORE, BUYER, cmd.idempotencyKey(), new Request(3L, reversed)))
                        .purchaseId())
                .isEqualTo(d.purchaseId());
        add(STORE, "SKU-1001-BLACK", 1, 4);
        assertThat(multi.create(cmd).purchaseId()).isEqualTo(d.purchaseId());
        assertThat(cart.read(STORE, BUYER).items()).hasSize(2);
        assertThat(count("orders")).isEqualTo(orders);
        assertThatThrownBy(() -> shop.create(new com.resolveflow.shared.shopping.ShoppingWire.DraftCommand(
                        STORE,
                        BUYER,
                        cmd.idempotencyKey(),
                        cmd.request().lines().getFirst())))
                .isInstanceOf(ShoppingService.Refused.class);
        assertThatThrownBy(() -> multi.create(new Command(
                        STORE,
                        BUYER,
                        cmd.idempotencyKey(),
                        new Request(4L, cmd.request().lines()))))
                .isInstanceOf(ShoppingService.Refused.class);
        assertThatThrownBy(() -> purchases.read(d.purchaseId(), STORE, "OTHER"))
                .isInstanceOf(ShoppingService.Refused.class);
    }

    @Test
    void cartAndPriceConflictsAndDelistingPreserveAllRows() {
        var c = setup();
        jdbc.update("UPDATE catalog_sku SET unit_amount=33900,version=2 WHERE sku_id='SKU-1001-BLACK'");
        assertThatThrownBy(() -> multi.create(c))
                .isInstanceOf(ShoppingService.Refused.class)
                .hasMessageContaining("报价");
        assertThat(cart.read(STORE, BUYER).items()).hasSize(2);
        jdbc.update("UPDATE catalog_product SET listed=FALSE WHERE product_id='P-1001'");
        assertThatThrownBy(() -> multi.create(c)).isInstanceOf(ShoppingService.Refused.class);
        jdbc.update("UPDATE catalog_product SET listed=TRUE WHERE product_id='P-1001'");
        jdbc.update("UPDATE catalog_sku SET unit_amount=32900,version=1 WHERE sku_id='SKU-1001-BLACK'");
        add(STORE, "SKU-1002-WHITE", 3, 2);
        assertThatThrownBy(() -> multi.create(c))
                .isInstanceOf(ShoppingService.Refused.class)
                .hasMessageContaining("购物车已更新");
        assertThat(cart.read(STORE, BUYER).items()).hasSize(2);
    }

    @Test
    void malformedMixedDuplicateAndOversizedRequestsCannotCreateDraft() {
        var c = setup();
        int drafts = count("checkout_draft");
        for (var ids : List.of(List.<String>of(), List.of("SKU-1001-BLACK", "SKU-1001-BLACK")))
            assertThatThrownBy(() -> multi.quote(new QuoteCommand(STORE, BUYER, new QuoteRequest(2L, ids))))
                    .isInstanceOf(IllegalArgumentException.class);
        assertThatThrownBy(() ->
                        multi.quote(new QuoteCommand(STORE, BUYER, new QuoteRequest(2L, List.of("SKU-2001-CREAM")))))
                .isInstanceOf(ShoppingService.Refused.class);
        assertThatThrownBy(() -> multi.create(new Command(
                        STORE, BUYER, key(), new Request(2L, List.of(new DraftRequest("SKU-1001-BLACK", 2, 1L))))))
                .isInstanceOf(ShoppingService.Refused.class);
        jdbc.update("UPDATE catalog_sku SET unit_amount=100000000,version=2 WHERE sku_id='SKU-1001-BLACK'");
        cart.write(new com.resolveflow.shared.shopping.CartWire.Command(
                STORE,
                BUYER,
                key(),
                new com.resolveflow.shared.shopping.CartWire.Request("SKU-1001-BLACK", 10, 2L, 2L)));
        assertThatThrownBy(() -> multi.quote(new QuoteCommand(
                        STORE, BUYER, new QuoteRequest(3L, List.of("SKU-1001-BLACK", "SKU-1002-WHITE")))))
                .isInstanceOf(IllegalArgumentException.class);
        assertThat(count("checkout_draft")).isEqualTo(drafts);
    }

    @Test
    void fullPaymentPublishesOriginalSnapshotsAndOneLedgerWithAllFreeSlots() {
        var cmd = setup();
        var d = multi.create(cmd);
        jdbc.update("UPDATE catalog_sku SET unit_amount=33900,version=2 WHERE sku_id='SKU-1001-BLACK'");
        jdbc.update("UPDATE catalog_product SET listed=FALSE WHERE product_id='P-1001'");
        assertThat(multi.create(cmd).totalAmount()).isEqualTo(72700);
        doAnswer(inv -> {
                    assertThat(org.springframework.transaction.support.TransactionSynchronizationManager
                                    .isActualTransactionActive())
                            .isFalse();
                    return inv.callRealMethod();
                })
                .when(provider)
                .charge(anyString(), anyLong());
        var c = pay();
        var p = payments.pay(d.draftId(), c);
        assertThat(p.status()).isEqualTo("SUCCEEDED");
        var result = purchases.read(d.purchaseId(), STORE, BUYER);
        assertThat(result.lines()).hasSize(2);
        assertThat(result.lines()).extracting(Line::lineAmount).containsExactly(32900L, 39800L);
        assertThat(result.lines()).extracting(Line::lineId).doesNotContainNull().doesNotHaveDuplicates();
        assertThat(result.lines().getFirst().lineId()).isEqualTo(p.lineId());
        assertThat(jdbc.queryForObject(
                        "SELECT paid_amount FROM payment_ledger WHERE order_id=?", Long.class, p.orderId()))
                .isEqualTo(72700);
        assertThat(jdbc.queryForList(
                        "SELECT l.line_paid_amount FROM order_line l WHERE order_id=? ORDER BY sku",
                        Long.class,
                        p.orderId()))
                .containsExactly(32900L, 39800L);
        assertThat(jdbc.queryForList(
                        "SELECT f.state FROM line_refund f JOIN order_line l ON l.line_id=f.line_id WHERE l.order_id=?",
                        String.class,
                        p.orderId()))
                .containsExactly("FREE", "FREE");
        assertThat(payments.pay(d.draftId(), c)).isEqualTo(p);
        assertThat(purchases.list(STORE, BUYER, "PAID", null, 24).items()).hasSize(1);
    }

    @Test
    void unknownKeepsOriginalAttemptAndAllPreallocatedLineIds() {
        var d = multi.create(setup());
        var c = pay();
        doThrow(new SimulatedCheckoutProvider.Uncertain()).when(provider).charge(anyString(), anyLong());
        var p = payments.pay(d.draftId(), c);
        assertThat(p.status()).isEqualTo("UNKNOWN");
        var ids = jdbc.queryForList(
                "SELECT line_id FROM checkout_payment_line WHERE attempt_id=? ORDER BY sku_id",
                String.class,
                p.attemptId());
        assertThat(ids).hasSize(2);
        assertThat(purchases.read(d.purchaseId(), STORE, BUYER).lines())
                .extracting(Line::lineId)
                .containsOnlyNulls();
        assertThatThrownBy(() -> payments.pay(d.draftId(), pay())).isInstanceOf(ShoppingService.Refused.class);
        reset(provider);
        var done = payments.pay(d.draftId(), c);
        assertThat(done.attemptId()).isEqualTo(p.attemptId());
        assertThat(purchases.read(d.purchaseId(), STORE, BUYER).lines())
                .extracting(Line::lineId)
                .containsExactlyElementsOf(ids);
    }

    @Test
    void determinedFailureCanStartNewAttemptButNeverRestoresCartOrPublishesOldIds() {
        var d = multi.create(setup());
        var c = pay();
        doAnswer(inv -> {
                    String attempt = inv.getArgument(0);
                    long amount = inv.getArgument(1);
                    var now = java.time.Instant.now().truncatedTo(java.time.temporal.ChronoUnit.MICROS);
                    jdbc.update(
                            "INSERT INTO simulated_checkout_receipt VALUES(?,?,'FAILED',?)",
                            attempt,
                            amount,
                            java.sql.Timestamp.from(now));
                    return new SimulatedCheckoutProvider.Receipt(attempt, amount, "FAILED", now);
                })
                .when(provider)
                .charge(anyString(), anyLong());
        var failed = payments.pay(d.draftId(), c);
        assertThat(failed.status()).isEqualTo("FAILED");
        assertThat(payments.pay(d.draftId(), c)).isEqualTo(failed);
        assertThat(cart.read(STORE, BUYER).items()).isEmpty();
        assertThat(purchases.read(d.purchaseId(), STORE, BUYER).status()).isEqualTo("WAITING_PAYMENT");
        var old = jdbc.queryForList(
                "SELECT line_id FROM checkout_payment_line WHERE attempt_id=?", String.class, failed.attemptId());
        reset(provider);
        var paid = payments.pay(d.draftId(), pay());
        assertThat(paid.status()).isEqualTo("SUCCEEDED");
        assertThat(paid.attemptId()).isNotEqualTo(failed.attemptId());
        assertThat(purchases.read(d.purchaseId(), STORE, BUYER).lines())
                .extracting(Line::lineId)
                .doesNotContainAnyElementsOf(old);
        assertThat(jdbc.queryForObject("SELECT COUNT(*) FROM order_line WHERE buyer_id=?", Integer.class, BUYER))
                .isEqualTo(2);
    }

    @Test
    void secondLineFailureRollsBackEntirePublicationAndReceiptRecoversSameIds() {
        var d = multi.create(setup());
        var c = pay();
        int orders = count("orders"), ledgers = count("payment_ledger");
        doAnswer(inv -> {
                    var args = (Object[]) inv.getRawArguments()[1];
                    if (inv.<String>getArgument(0).startsWith("INSERT INTO order_line")
                            && java.util.Arrays.asList(args).contains(BUYER)
                            && java.util.Arrays.asList(args).contains("SKU-1002-WHITE"))
                        throw new org.springframework.dao.DataIntegrityViolationException(
                                "synthetic second line failure");
                    return inv.callRealMethod();
                })
                .when(jdbc)
                .update(anyString(), any(Object[].class));
        assertThatThrownBy(() -> payments.pay(d.draftId(), c))
                .isInstanceOf(org.springframework.dao.DataAccessException.class);
        assertThat(count("orders")).isEqualTo(orders);
        assertThat(count("payment_ledger")).isEqualTo(ledgers);
        assertThat(jdbc.queryForObject("SELECT COUNT(*) FROM order_line WHERE buyer_id=?", Integer.class, BUYER))
                .isZero();
        var original = payments.snapshot(d.draftId(), STORE, BUYER);
        assertThat(original.status()).isEqualTo("UNKNOWN");
        assertThat(provider.lookup(original.attemptId())).isNotNull();
        var ids = jdbc.queryForList(
                "SELECT line_id FROM checkout_payment_line WHERE attempt_id=? ORDER BY sku_id",
                String.class,
                original.attemptId());
        reset(jdbc);
        var p = payments.inspect(d.draftId(), STORE, BUYER);
        assertThat(p.status()).isEqualTo("SUCCEEDED");
        assertThat(p.attemptId()).isEqualTo(original.attemptId());
        assertThat(purchases.read(d.purchaseId(), STORE, BUYER).lines())
                .extracting(Line::lineId)
                .containsExactlyElementsOf(ids);
        assertThat(count("orders")).isEqualTo(orders + 1);
        assertThat(count("payment_ledger")).isEqualTo(ledgers + 1);
    }

    @Test
    void cartDeleteFailureRollsBackDraftAndEverySelectedItem() {
        var c = setup();
        int drafts = count("checkout_draft");
        doAnswer(inv -> {
                    var args = (Object[]) inv.getRawArguments()[1];
                    if (inv.<String>getArgument(0).startsWith("DELETE FROM shopping_cart_item")
                            && java.util.Arrays.asList(args).contains(BUYER)
                            && java.util.Arrays.asList(args).contains("SKU-1002-WHITE"))
                        throw new org.springframework.dao.DataIntegrityViolationException(
                                "synthetic cart delete failure");
                    return inv.callRealMethod();
                })
                .when(jdbc)
                .update(anyString(), any(Object[].class));
        assertThatThrownBy(() -> multi.create(c)).isInstanceOf(org.springframework.dao.DataAccessException.class);
        assertThat(count("checkout_draft")).isEqualTo(drafts);
        assertThat(cart.read(STORE, BUYER).items()).hasSize(2);
        assertThat(cart.read(STORE, BUYER).revision()).isEqualTo(2);
        reset(jdbc);
        assertThat(multi.create(c).lines()).hasSize(2);
    }

    @Test
    void concurrentCreatesAndPaymentsPublishOneOrderAndDoNotDeleteTwice() throws Exception {
        var c = setup();
        Purchase d;
        try (var pool = Executors.newFixedThreadPool(2)) {
            var a = pool.submit(() -> multi.create(c));
            var b = pool.submit(() -> multi.create(c));
            d = a.get();
            assertThat(b.get().purchaseId()).isEqualTo(d.purchaseId());
            assertThat(cart.read(STORE, BUYER).revision()).isEqualTo(3);
            var pay = pay();
            var x = pool.submit(() -> payments.pay(d.draftId(), pay));
            var y = pool.submit(() -> payments.pay(d.draftId(), pay));
            assertThat(x.get()).isEqualTo(y.get());
        }
        assertThat(jdbc.queryForObject("SELECT COUNT(*) FROM orders WHERE buyer_id=?", Integer.class, BUYER))
                .isEqualTo(1);
        assertThat(jdbc.queryForObject("SELECT COUNT(*) FROM order_line WHERE buyer_id=?", Integer.class, BUYER))
                .isEqualTo(2);
    }

    @Test
    void incompleteSnapshotRefusesBeforeProviderAndCancellationDoesNotRestoreCart() {
        var d = multi.create(setup());
        jdbc.update("DELETE FROM checkout_draft_line WHERE draft_id=? AND sku_id='SKU-1002-WHITE'", d.draftId());
        assertThatThrownBy(() -> payments.pay(d.draftId(), pay())).isInstanceOf(IllegalStateException.class);
        verify(provider, never()).charge(anyString(), anyLong());
        assertThat(jdbc.queryForObject(
                        "SELECT COUNT(*) FROM checkout_payment_attempt WHERE draft_id=?", Integer.class, d.draftId()))
                .isZero();
        payments.cancel(d.draftId(), new ScopeCommand(STORE, BUYER));
        assertThat(cart.read(STORE, BUYER).items()).isEmpty();
    }
}
