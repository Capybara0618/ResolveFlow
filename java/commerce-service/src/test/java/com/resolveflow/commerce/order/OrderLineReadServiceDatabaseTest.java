package com.resolveflow.commerce.order;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

import com.resolveflow.commerce.CommerceDatabaseTest;
import java.time.Instant;
import java.util.List;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.jdbc.core.JdbcTemplate;

/**
 * The order-line read model against real MySQL with the real migrations and seed.
 *
 * <p>The subject is the scope rule: a caller sees its own merchant's lines, a customer sees only
 * their own, and combining the two is what makes the isolation hold. The seed is fixed
 * (V2__demo_order_seed.sql), so a failure here means the read path or the SQL changed, not that the
 * data moved.
 */
class OrderLineReadServiceDatabaseTest extends CommerceDatabaseTest {

    private static final String ORDER_A = "00000000-0000-4000-8000-0000000000aa";
    private static final String ORDER_C = "00000000-0000-4000-8000-0000000000cc";

    @Autowired
    OrderLineReadService service;

    @Autowired
    JdbcTemplate jdbc;

    @Test
    @DisplayName("a customer sees their own lines, newest first, exactly as seeded")
    void aCustomerSeesTheirOwnLines() {
        OrderLineReadService.Page page = service.list("M-1001", "C-2002", null, null);

        assertThat(page.items()).extracting(OrderLineRow::lineId).containsExactly("7002", "7001");
        assertThat(page.nextCursor()).isNull();
        OrderLineRow line = page.items().get(0);
        assertThat(line.orderId()).isEqualTo(ORDER_A);
        assertThat(line.sku()).isEqualTo("SKU-BLUE-L");
        assertThat(line.quantity()).isEqualTo(1);
        assertThat(line.linePaidAmount()).isEqualTo(1999);
        assertThat(line.currency()).isEqualTo("CNY");
        assertThat(line.status()).isEqualTo("PAID");
        assertThat(line.version()).isEqualTo(1);
        // The seeded instant is UTC; a driver left on the JVM zone would return 00:15Z or 16:15Z.
        assertThat(line.paidAt()).isEqualTo(Instant.parse("2026-09-10T08:15:00Z"));
    }

    @Test
    @DisplayName("a customer identifier is only meaningful inside its merchant")
    void aCustomerIdentifierDoesNotCrossMerchants() {
        // C-2002 belongs to M-1001. Asking for it under M-1002 must not fall back to "any customer".
        assertThat(service.list("M-1002", "C-2002", null, null).items()).isEmpty();
        assertThat(service.list("M-1001", "C-2003", null, null).items())
                .extracting(OrderLineRow::lineId)
                .containsExactly("7101");
        assertThat(service.list("M-1002", "C-2004", null, null).items())
                .extracting(OrderLineRow::lineId)
                .containsExactly("7201");
    }

    @Test
    @DisplayName("a merchant-scoped caller sees the whole merchant and nothing else")
    void aMerchantScopeSeesItsOwnLines() {
        OrderLineReadService.Page page = service.list("M-1001", null, null, null);

        assertThat(page.items()).extracting(OrderLineRow::lineId).containsExactly("7101", "7002", "7001");
        assertThat(page.items()).extracting(OrderLineRow::orderId).doesNotContain(ORDER_C);
    }

    @Test
    @DisplayName("paging walks every row exactly once and then says there is no more")
    void pagingIsStableAndExhaustive() {
        List<String> seen = new java.util.ArrayList<>();
        String cursor = null;
        for (int guard = 0; guard < 10; guard++) {
            OrderLineReadService.Page page = service.list("M-1001", null, cursor, 1);
            seen.addAll(page.items().stream().map(OrderLineRow::lineId).toList());
            cursor = page.nextCursor();
            if (cursor == null) {
                break;
            }
        }

        assertThat(seen).containsExactly("7101", "7002", "7001");
    }

    @Test
    @DisplayName("the limit defaults to 20 and refuses a value outside the documented range")
    void theLimitIsBounded() {
        assertThat(service.list("M-1001", null, null, null).limit()).isEqualTo(20);
        assertThat(service.list("M-1001", null, null, 100).limit()).isEqualTo(100);
        assertThatThrownBy(() -> service.list("M-1001", null, null, 0))
                .isInstanceOf(IllegalArgumentException.class)
                .hasMessageContaining("limit");
        assertThatThrownBy(() -> service.list("M-1001", null, null, 101))
                .isInstanceOf(IllegalArgumentException.class)
                .hasMessageContaining("limit");
        assertThatThrownBy(() -> service.list(" ", null, null, null))
                .isInstanceOf(IllegalArgumentException.class)
                .hasMessageContaining("merchant scope");
    }

    @Test
    @DisplayName("a cursor this service did not issue is refused, not guessed at")
    void aForeignCursorIsRefused() {
        assertThatThrownBy(() -> service.list("M-1001", null, "not-a-cursor", null))
                .isInstanceOf(OrderLineCursor.InvalidCursorException.class);
        assertThatThrownBy(() -> service.list("M-1001", null, "Zm9v", null))
                .isInstanceOf(OrderLineCursor.InvalidCursorException.class);
    }

    @Test
    @DisplayName("an order filter narrows the scope and cannot escape it")
    void anOrderFilterCannotEscapeTheScope() {
        // C01.2c: Case reads one order through this filter. Naming an order that is not in the
        // scope must yield nothing, so Case can answer 404 without disclosing that it exists.
        assertThat(service.listByOrder("M-1001", "C-2002", ORDER_A, null, null).items())
                .extracting(OrderLineRow::lineId)
                .containsExactly("7002", "7001");
        assertThat(service.listByOrder("M-1002", "C-2004", ORDER_A, null, null).items())
                .as("order %s belongs to M-1001/C-2002, not to this scope", ORDER_A)
                .isEmpty();
        assertThat(service.listByOrder("M-1001", "C-2003", ORDER_A, null, null).items())
                .as("same merchant, different customer: still not theirs")
                .isEmpty();
    }

    @Test
    void anUnknownScopeIsEmpty() {
        assertThat(service.list("M-9999", null, null, null).items()).isEmpty();
    }

    @Test
    @DisplayName("the database refuses to reserve more than the order was paid")
    void theLedgerInvariantIsEnforcedByTheSchema() {
        // 订单已退+预留不超过支付额 (docs/product-spec.md:13, docs/domain-model.md:41). The refund
        // path locks and checks this row; the CHECK constraint is the last line of defence, and a
        // database that does not enforce it would let a code path slip through unnoticed.
        //
        // MySQL reports a CHECK violation as SQLState HY000 / error 3819, which Spring does not
        // translate into DataIntegrityViolationException, so the assertion is the common
        // DataAccessException plus the constraint name. Worth remembering for C05: a refund path
        // leaning on this constraint must handle an untranslated DataAccessException as well.
        assertThatThrownBy(() -> jdbc.update(
                        "UPDATE payment_ledger SET reserved_refund_amount = paid_amount + 1 WHERE order_id = ?",
                        ORDER_A))
                .isInstanceOf(org.springframework.dao.DataAccessException.class)
                .hasMessageContaining("chk_payment_ledger_within_paid");
        assertThat(jdbc.queryForObject(
                        "SELECT reserved_refund_amount FROM payment_ledger WHERE order_id = ?", Long.class, ORDER_A))
                .isZero();
    }

    @Test
    @DisplayName("the schema refuses a quantity or an amount the contract forbids")
    void theLineConstraintsAreEnforced() {
        assertThatThrownBy(() -> jdbc.update(
                        "INSERT INTO order_line (line_id, order_id, merchant_id, customer_id, sku, category,"
                                + " quantity, line_paid_amount, currency, paid_at, order_status, version)"
                                + " VALUES ('7999', ?, 'M-1001', 'C-2002', 'SKU-X', 'apparel', 0, 100, 'CNY',"
                                + " '2026-09-10 08:15:00.000000', 'PAID', 1)",
                        ORDER_A))
                .isInstanceOf(org.springframework.dao.DataAccessException.class)
                .hasMessageContaining("chk_order_line_quantity");
    }
}
