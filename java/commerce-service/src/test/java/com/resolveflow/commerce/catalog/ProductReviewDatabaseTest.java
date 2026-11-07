package com.resolveflow.commerce.catalog;

import static org.assertj.core.api.Assertions.*;

import com.resolveflow.commerce.CommerceDatabaseTest;
import com.resolveflow.shared.shopping.CheckoutWire.*;
import com.resolveflow.shared.shopping.ProductReviewWire.*;
import com.resolveflow.shared.shopping.ShoppingWire.*;
import java.util.UUID;
import java.util.concurrent.Executors;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.jdbc.core.JdbcTemplate;

class ProductReviewDatabaseTest extends CommerceDatabaseTest {
    @Autowired
    ProductReviewService reviews;

    @Autowired
    ShoppingService shop;

    @Autowired
    CheckoutPayments payments;

    @Autowired
    JdbcTemplate jdbc;

    private static final String CUSTOMER = "REVIEW-TEST";

    private Payment purchase(boolean delivered) {
        var d = shop.create(new DraftCommand(
                "M-1001", CUSTOMER, UUID.randomUUID().toString(), new DraftRequest("SKU-1001-BLACK", 1, 1L)));
        var p = payments.pay(
                d.draftId(),
                new PayCommand("M-1001", CUSTOMER, UUID.randomUUID().toString()));
        if (delivered)
            jdbc.update(
                    "UPDATE shipment SET status='DELIVERED',carrier_conclusion='DELIVERED',source_version=2 WHERE line_id=?",
                    p.lineId());
        return p;
    }

    private Command command(long rating, String body, long version) {
        return new Command("M-1001", CUSTOMER, new Write(rating, body, version));
    }

    @Test
    void epochAdvancesOnlyForDistinctContentAndRejectsCrossStoreCatalogMapping() {
        var p = purchase(true);
        long epoch = reviews.publicEpoch("P-1001");
        var r = reviews.save(p.lineId(), command(5, "epoch", 0));
        assertThat(reviews.publicEpoch("P-1001")).isEqualTo(epoch + 1);
        reviews.save(p.lineId(), command(5, "epoch", 0));
        assertThat(reviews.publicEpoch("P-1001")).isEqualTo(epoch + 1);
        assertThatThrownBy(() -> reviews.save(p.lineId(), command(1, "stale", 0)))
                .isInstanceOf(ShoppingService.Refused.class);
        assertThat(reviews.publicEpoch("P-1001")).isEqualTo(epoch + 1);
        reviews.reply(r.reviewId(), new ReplyCommand("M-1001", new Reply("reply", r.version())));
        assertThat(reviews.publicEpoch("P-1001")).isEqualTo(epoch + 2);
        var q = purchase(true);
        jdbc.update("UPDATE order_line SET sku='SKU-2001-CREAM' WHERE line_id=?", q.lineId());
        assertThat(reviews.own(q.lineId(), "M-1001", CUSTOMER).canReview()).isFalse();
        assertThatThrownBy(() -> reviews.save(q.lineId(), command(5, "wrong mapping", 0)))
                .isInstanceOf(ShoppingService.Refused.class);
    }

    @Test
    void requiresOwnershipAndDeliveryAndNeverChangesPayment() {
        var p = purchase(false);
        assertThat(reviews.own(p.lineId(), "M-1001", CUSTOMER).canReview()).isFalse();
        assertThatThrownBy(() -> reviews.save(p.lineId(), command(5, "good", 0)))
                .isInstanceOf(ShoppingService.Refused.class);
        assertThatThrownBy(() -> reviews.own(p.lineId(), "M-1001", "OTHER"))
                .isInstanceOf(ShoppingService.Refused.class);
        assertThatThrownBy(() -> reviews.own(p.lineId(), "M-1002", CUSTOMER))
                .isInstanceOf(ShoppingService.Refused.class);
        assertThat(jdbc.queryForObject(
                        "SELECT reserved_refund_amount+refunded_amount FROM payment_ledger WHERE order_id=?",
                        Long.class,
                        p.orderId()))
                .isZero();
    }

    @Test
    void createReplayModifyAndOldVersionConflict() {
        var p = purchase(true);
        var first = reviews.save(p.lineId(), command(5, " good ", 0));
        assertThat(first.body()).isEqualTo("good");
        assertThat(reviews.save(p.lineId(), command(5, "good", 0))).isEqualTo(first);
        var second = reviews.save(p.lineId(), command(2, "changed", first.version()));
        assertThat(second.reviewId()).isEqualTo(first.reviewId());
        assertThat(second.version()).isEqualTo(first.version() + 1);
        assertThatThrownBy(() -> reviews.save(p.lineId(), command(1, "stale", first.version())))
                .isInstanceOf(ShoppingService.Refused.class);
        assertThat(reviews.own(p.lineId(), "M-1001", CUSTOMER).review()).isEqualTo(second);
    }

    @Test
    void concurrentFirstReviewsProduceOneRow() throws Exception {
        var p = purchase(true);
        try (var pool = Executors.newFixedThreadPool(2)) {
            var a = pool.submit(() -> reviews.save(p.lineId(), command(5, "same", 0)));
            var b = pool.submit(() -> reviews.save(p.lineId(), command(5, "same", 0)));
            assertThat(a.get().reviewId()).isEqualTo(b.get().reviewId());
        }
        assertThat(jdbc.queryForObject(
                        "SELECT COUNT(*) FROM product_review WHERE line_id=?", Integer.class, p.lineId()))
                .isEqualTo(1);
    }

    @Test
    void onlyOwningMerchantCanReplyAndMustUseCurrentVersion() {
        var p = purchase(true);
        var r = reviews.save(p.lineId(), command(4, "okay", 0));
        assertThatThrownBy(() ->
                        reviews.reply(r.reviewId(), new ReplyCommand("M-1002", new Reply("hello", r.version()))))
                .isInstanceOf(ShoppingService.Refused.class);
        var replied = reviews.reply(r.reviewId(), new ReplyCommand("M-1001", new Reply("thanks", r.version())));
        assertThat(replied.reply()).isEqualTo("thanks");
        assertThat(reviews.reply(r.reviewId(), new ReplyCommand("M-1001", new Reply("thanks", r.version()))))
                .isEqualTo(replied);
        assertThatThrownBy(() ->
                        reviews.reply(r.reviewId(), new ReplyCommand("M-1001", new Reply("different", r.version()))))
                .isInstanceOf(ShoppingService.Refused.class);
        assertThat(reviews.merchantPage("M-1002", null, 20).items()).noneMatch(x -> x.reviewId() == r.reviewId());
    }

    @Test
    void summaryMatchesDatabaseAfterEditsAndRefundDoesNotRemoveReview() {
        var p = purchase(true);
        var r = reviews.save(p.lineId(), command(1, "honest", 0));
        reviews.save(p.lineId(), command(3, "updated", r.version()));
        jdbc.update("UPDATE payment_ledger SET refunded_amount=paid_amount WHERE order_id=?", p.orderId());
        var page = reviews.publicPage("P-1001", null, 20);
        assertThat(page.items()).anyMatch(x -> x.reviewId() == r.reviewId() && x.rating() == 3);
        assertThat(page.summary().count())
                .isEqualTo(jdbc.queryForObject(
                        "SELECT COUNT(*) FROM product_review WHERE product_id='P-1001'", Long.class));
        assertThat(page.summary().stars().stream().mapToLong(Long::longValue).sum())
                .isEqualTo(page.summary().count());
        assertThat(page.summary().average())
                .isEqualTo(jdbc.queryForObject(
                        "SELECT ROUND(AVG(rating),1) FROM product_review WHERE product_id='P-1001'", Double.class));
        var json = new tools.jackson.databind.ObjectMapper().writeValueAsString(page);
        assertThat(json).doesNotContain(CUSTOMER, p.lineId(), p.orderId(), "buyer_id", "merchant_id");
    }

    @Test
    void validatesInputsAndStablePagination() {
        var p = purchase(true);
        assertThatThrownBy(() -> reviews.save(p.lineId(), command(6, "invalid", 0)))
                .isInstanceOf(IllegalArgumentException.class);
        assertThatThrownBy(() -> reviews.save(p.lineId(), command(1, " ", 0)))
                .isInstanceOf(IllegalArgumentException.class);
        assertThatThrownBy(() -> reviews.publicPage("P-1001", null, 21)).isInstanceOf(IllegalArgumentException.class);
        reviews.save(p.lineId(), command(4, "one", 0));
        var q = purchase(true);
        reviews.save(q.lineId(), command(5, "two", 0));
        var first = reviews.publicPage("P-1001", null, 1);
        assertThat(first.nextBefore()).isNotNull();
        var next = reviews.publicPage("P-1001", first.nextBefore(), 1);
        assertThat(next.items())
                .noneMatch(x -> x.reviewId() == first.items().getFirst().reviewId());
    }
}
