package com.resolveflow.commerce.catalog;

import static org.assertj.core.api.Assertions.*;

import com.resolveflow.commerce.CommerceDatabaseTest;
import com.resolveflow.shared.shopping.CheckoutWire.PayCommand;
import com.resolveflow.shared.shopping.ShippingWire.*;
import com.resolveflow.shared.shopping.ShoppingWire.*;
import java.util.UUID;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.jdbc.core.JdbcTemplate;

class CheckoutShippingDatabaseTest extends CommerceDatabaseTest {
    @Autowired
    ShoppingService shop;

    @Autowired
    CheckoutPayments payments;

    @Autowired
    JdbcTemplate db;

    @Autowired
    CartService cart;

    @Autowired
    MultiCheckoutService multi;

    static final String MERCHANT = "M-1001", BUYER = "TEST-SHIPPING";
    final Selection choice = new Selection(UUID.randomUUID().toString(), 1L);
    final Snapshot address = new Snapshot(choice.address_id(), 1, "测试收货人", "13000000000", "测试省", "测试市", "测试区", "测试路1号");

    DraftCommand command(String key, Selection selected, Snapshot snapshot) {
        return new DraftCommand(MERCHANT, BUYER, key, new DraftRequest("SKU-1001-BLACK", 1, 1L, selected), snapshot);
    }

    @Test
    void snapshotSurvivesPaymentAndIdempotentRetryWithoutRereadingAddressBook() {
        String key = UUID.randomUUID().toString();
        var d = shop.create(command(key, choice, address));
        var reads = new CheckoutShipping(db);
        assertThat(reads.buyer("draft:" + d.draftId(), MERCHANT, BUYER).shipping())
                .isEqualTo(address);
        assertThat(shop.create(command(key, choice, null)).draftId()).isEqualTo(d.draftId());
        var paid = payments.pay(
                d.draftId(), new PayCommand(MERCHANT, BUYER, UUID.randomUUID().toString()));
        assertThat(paid.status()).isEqualTo("SUCCEEDED");
        assertThat(reads.buyer("order:" + paid.orderId(), MERCHANT, BUYER).shipping())
                .isEqualTo(address);
        assertThat(reads.merchant(paid.orderId(), MERCHANT).shipping()).isEqualTo(address);
        assertThatThrownBy(() -> reads.buyer("order:" + paid.orderId(), MERCHANT, "OTHER"))
                .isInstanceOf(ShoppingService.Refused.class);
        assertThatThrownBy(() -> reads.merchant(paid.orderId(), "M-1002")).isInstanceOf(ShoppingService.Refused.class);
    }

    @Test
    void missingSnapshotDoesNotCreateDraftAndSameKeyCannotChangeAddress() {
        String key = UUID.randomUUID().toString();
        assertThatThrownBy(() -> shop.create(command(key, choice, null))).isInstanceOf(ShoppingService.Refused.class);
        assertThat(db.queryForObject("SELECT COUNT(*) FROM checkout_draft WHERE idempotency_key=?", Integer.class, key))
                .isZero();
        var d = shop.create(command(key, choice, address));
        var changed = new Snapshot(
                address.address_id(),
                1,
                "不同收货人",
                address.phone(),
                address.province(),
                address.city(),
                address.district(),
                address.detail());
        assertThatThrownBy(() -> shop.create(command(key, choice, changed)))
                .isInstanceOf(ShoppingService.Refused.class);
        assertThatThrownBy(() -> shop.create(command(key, new Selection(choice.address_id(), 2L), null)))
                .isInstanceOf(ShoppingService.Refused.class);
        assertThat(new CheckoutShipping(db)
                        .buyer("draft:" + d.draftId(), MERCHANT, BUYER)
                        .shipping())
                .isEqualTo(address);
    }

    @Test
    void cartCheckoutKeepsTheSameSnapshotAfterCartConsumptionAndRetry() {
        String customer = "SHIPPING-CART-" + UUID.randomUUID();
        cart.write(new com.resolveflow.shared.shopping.CartWire.Command(
                MERCHANT,
                customer,
                UUID.randomUUID().toString(),
                new com.resolveflow.shared.shopping.CartWire.Request("SKU-1001-BLACK", 1, 0L, 1L)));
        var request = new com.resolveflow.shared.shopping.MultiCheckoutWire.Request(
                1L, java.util.List.of(new DraftRequest("SKU-1001-BLACK", 1, 1L)), choice);
        String key = UUID.randomUUID().toString();
        var purchase = multi.create(new com.resolveflow.shared.shopping.MultiCheckoutWire.Command(
                MERCHANT, customer, key, request, address));
        assertThat(new CheckoutShipping(db)
                        .buyer(purchase.purchaseId(), MERCHANT, customer)
                        .shipping())
                .isEqualTo(address);
        assertThat(multi.create(new com.resolveflow.shared.shopping.MultiCheckoutWire.Command(
                                MERCHANT, customer, key, request))
                        .purchaseId())
                .isEqualTo(purchase.purchaseId());
    }

    @Autowired
    PurchaseReads purchases;

    @Test
    void shoppingStageTracksShippingAndRefundFactsWithoutChangingPaymentState() {
        var d = shop.create(command(UUID.randomUUID().toString(), choice, address));
        var paid = payments.pay(
                d.draftId(), new PayCommand(MERCHANT, BUYER, UUID.randomUUID().toString()));
        String id = "draft:" + d.draftId();
        assertThat(purchases.read(id, MERCHANT, BUYER).shoppingStage()).isEqualTo("AWAITING_SHIPMENT");
        assertThat(purchases
                        .list(MERCHANT, BUYER, "AWAITING_SHIPMENT", null, 48)
                        .items())
                .extracting(com.resolveflow.shared.shopping.CheckoutWire.Purchase::purchaseId)
                .contains(id);
        db.update(
                "UPDATE shipment SET status='IN_TRANSIT',carrier_conclusion='IN_TRANSIT' WHERE line_id=?",
                paid.lineId());
        assertThat(purchases.read(id, MERCHANT, BUYER).shoppingStage()).isEqualTo("AWAITING_RECEIPT");
        db.update(
                "UPDATE shipment SET status='DELIVERED',carrier_conclusion='DELIVERED' WHERE line_id=?", paid.lineId());
        assertThat(purchases.read(id, MERCHANT, BUYER).shoppingStage()).isEqualTo("COMPLETED");
        db.update("UPDATE payment_ledger SET refunded_amount=paid_amount WHERE order_id=?", paid.orderId());
        assertThat(purchases.read(id, MERCHANT, BUYER).shoppingStage()).isEqualTo("AFTER_SALES");
        assertThat(purchases.read(id, MERCHANT, BUYER).status()).isEqualTo("PAID");
        assertThat(purchases.list(MERCHANT, BUYER, "COMPLETED", null, 48).items())
                .extracting(com.resolveflow.shared.shopping.CheckoutWire.Purchase::purchaseId)
                .doesNotContain(id);
    }
}
