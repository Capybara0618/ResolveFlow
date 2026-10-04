package com.resolveflow.commerce.catalog;

import static org.assertj.core.api.Assertions.assertThat;

import com.resolveflow.commerce.CommerceDatabaseTest;
import com.resolveflow.commerce.order.OrderLineReadService;
import com.resolveflow.shared.shopping.CheckoutWire.PayCommand;
import com.resolveflow.shared.shopping.FulfillmentWire.ShipCommand;
import com.resolveflow.shared.shopping.ShoppingWire.DraftCommand;
import com.resolveflow.shared.shopping.ShoppingWire.DraftRequest;
import java.util.UUID;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;

class AgentOrderFactsDatabaseTest extends CommerceDatabaseTest {
    @Autowired
    ShoppingService shop;

    @Autowired
    CheckoutPayments payments;

    @Autowired
    MerchantTradeService trades;

    @Autowired
    OrderLineReadService orders;

    @Test
    void paymentAndShipmentChangesAreVisibleWithoutInventingLegacyFulfillment() {
        var legacy = orders.readContext("7001").orElseThrow();
        assertThat(legacy.paymentVersion()).isPositive();
        assertThat(legacy.fulfillmentStatus()).isNull();
        assertThat(legacy.fulfillmentVersion()).isNull();
        var draft = shop.create(new DraftCommand(
                "M-1001", "AGENT-FACTS", UUID.randomUUID().toString(), new DraftRequest("SKU-1001-BLACK", 1, 1L)));
        var paid = payments.pay(
                draft.draftId(),
                new PayCommand("M-1001", "AGENT-FACTS", UUID.randomUUID().toString()));
        var line = orders.listByOrder("M-1001", "AGENT-FACTS", paid.orderId(), null, 20)
                .items()
                .getFirst();
        var before = orders.readContext(line.lineId()).orElseThrow();
        assertThat(before.orderStatus()).isEqualTo("PAID");
        assertThat(before.paidAt()).isNotNull();
        assertThat(before.paymentVersion()).isEqualTo(1L);
        assertThat(before.fulfillmentStatus()).isEqualTo("NOT_SHIPPED");
        assertThat(before.fulfillmentVersion()).isEqualTo(1L);
        trades.ship(
                paid.orderId(),
                new ShipCommand("M-1001", "test-merchant", UUID.randomUUID().toString(), 1L));
        var after = orders.readContext(line.lineId()).orElseThrow();
        assertThat(after.fulfillmentStatus()).isEqualTo("IN_TRANSIT");
        assertThat(after.fulfillmentVersion()).isEqualTo(2L);
        assertThat(after.paymentVersion()).isEqualTo(before.paymentVersion());
        assertThat(after.linePaidAmount()).isEqualTo(before.linePaidAmount());
    }
}
