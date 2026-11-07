package com.resolveflow.commerce.refund;

import static org.assertj.core.api.Assertions.*;

import com.resolveflow.commerce.CommerceDatabaseTest;
import com.resolveflow.commerce.order.LineRefundStatusRepository;
import com.resolveflow.commerce.order.OrderLineReadService;
import com.resolveflow.shared.contract.CanonicalJson;
import java.time.Instant;
import java.util.*;
import java.util.concurrent.*;
import org.junit.jupiter.api.*;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.test.context.bean.override.mockito.MockitoSpyBean;
import tools.jackson.databind.ObjectMapper;
import tools.jackson.databind.node.ObjectNode;

class MultiLineRefundDatabaseTest extends CommerceDatabaseTest {
    @Autowired
    JdbcTemplate jdbc;

    @Autowired
    RefundAcceptanceService acceptance;

    @Autowired
    RefundSettlementService settlement;

    @Autowired
    OrderLineReadService reads;

    @Autowired
    LineRefundStatusRepository statuses;

    @MockitoSpyBean
    RefundMoneyRepository money;

    @Autowired
    org.apache.ibatis.session.SqlSessionFactory sqlSessions;

    private final ObjectMapper json = new ObjectMapper();
    private final String merchant = "M-MULTILINE-TEST";
    private String order, a, b;

    @BeforeEach
    void seed() {
        order = UUID.randomUUID().toString();
        a = "multi-" + UUID.randomUUID();
        b = "multi-" + UUID.randomUUID();
        jdbc.update(
                "INSERT INTO orders(order_id,merchant_id,buyer_id,order_status,currency,paid_at) VALUES(?,?,?,'PAID','CNY',CURRENT_TIMESTAMP(6))",
                order,
                merchant,
                "C-MULTILINE");
        for (var line : List.of(a, b))
            jdbc.update(
                    "INSERT INTO order_line(line_id,order_id,merchant_id,buyer_id,sku,category,quantity,line_paid_amount,currency,paid_at,order_status,version) VALUES(?,?,?,?,?,'electronics',1,?,'CNY',CURRENT_TIMESTAMP(6),'PAID',1)",
                    line,
                    order,
                    merchant,
                    "C-MULTILINE",
                    line,
                    line.equals(a) ? 32900 : 39800);
        jdbc.update(
                "INSERT INTO payment_ledger(order_id,paid_amount,refunded_amount,reserved_refund_amount,version) VALUES(?,72700,0,0,1)",
                order);
        for (var line : List.of(a, b))
            jdbc.update(
                    "INSERT INTO line_refund(line_id,state,operation_id,version,updated_at) VALUES(?,'FREE',NULL,1,CURRENT_TIMESTAMP(6))",
                    line);
    }

    @AfterEach
    void cleanup() {
        // Only this test's fixtures, in disposable Testcontainers MySQL. Never the demo database.
        jdbc.update("DELETE FROM event_outbox WHERE merchant_id=?", merchant);
        jdbc.update(
                "DELETE FROM refund_request_inbox WHERE operation_id IN(SELECT operation_id FROM refund_operation WHERE merchant_id=?)",
                merchant);
        jdbc.update("DELETE FROM refund_operation WHERE merchant_id=?", merchant);
        jdbc.update("DELETE FROM line_refund WHERE line_id IN(?,?)", a, b);
        jdbc.update("DELETE FROM payment_ledger WHERE order_id=?", order);
        jdbc.update("DELETE FROM order_line WHERE order_id=?", order);
        jdbc.update("DELETE FROM orders WHERE order_id=?", order);
    }

    private ObjectNode command(String line) {
        var n = json.createObjectNode();
        n.put("operation_id", UUID.randomUUID().toString());
        n.put("case_id", UUID.randomUUID().toString());
        n.put("authorization_id", UUID.randomUUID().toString());
        n.put("input_revision", 1);
        n.put("line_id", line);
        n.put("merchant_id", merchant);
        n.put("action", "REFUND");
        n.put("quantity", 1);
        n.put("currency", "CNY");
        n.put("amount_minor", line.equals(a) ? 32900 : 39800);
        n.put("policy_version", "synthetic-multi");
        n.put("target_service", "commerce-service");
        n.put("payload_hash", CanonicalJson.payloadHash(n));
        return n;
    }

    private String accept(String line) {
        var n = command(line);
        return acceptance.accept(UUID.randomUUID().toString(), n).operation().operationId();
    }

    private void ledger(long refunded, long reserved) {
        assertThat(jdbc.queryForMap(
                        "SELECT refunded_amount,reserved_refund_amount FROM payment_ledger WHERE order_id=?", order))
                .containsEntry("refunded_amount", refunded)
                .containsEntry("reserved_refund_amount", reserved);
    }

    @Test
    void anotherLinesRefundMustNotBeSubtractedFromTheFreeLinesEntitlement() {
        var op = accept(a);
        settlement.settleSucceeded(op, "synthetic-a");
        ledger(32900, 0);
        var row = json.valueToTree(reads.readContext(b).orElseThrow());
        assertThat(row.path("orderPaidAmount").asLong()).isEqualTo(72700);
        assertThat(row.path("lineRefundState").asString()).isEqualTo("FREE");
        assertThat(row.path("refundedAmount").asLong()).isEqualTo(32900);
        var status = json.valueToTree(statuses.findRefundStatus(b));
        assertThat(status.path("lineRefundedAmount").asLong()).isZero();
        assertThat(status.path("lineReservedRefundAmount").asLong()).isZero();
        assertThat(status.path("orderPaidAmount").asLong()).isEqualTo(72700);
        settlement.settleSucceeded(accept(b), "synthetic-b");
        ledger(72700, 0);
        assertThatThrownBy(() -> accept(a)).isInstanceOf(RefundRejectedException.class);
    }

    @Test
    void unknownKeepsItsLineButAllowsAnotherWholeLineWithinTheRemainingOrderAmount() {
        var op = accept(a);
        settlement.settleUnknown(op, "synthetic-timeout", Instant.now().plusSeconds(60));
        ledger(0, 32900);
        assertThatThrownBy(() -> accept(a)).isInstanceOf(RefundRejectedException.class);
        var other = accept(b);
        ledger(0, 72700);
        settlement.settleSucceeded(other, "synthetic-b");
        ledger(39800, 32900);
        settlement.settleFailed(op, "synthetic-declined");
        ledger(39800, 0);
        settlement.settleSucceeded(accept(a), "synthetic-retry");
        ledger(72700, 0);
    }

    @Test
    void concurrentDeliveriesOfOneOperationAllReturnTheSameReservation() throws Exception {
        var reachedLedger = new CyclicBarrier(10);
        var realMoney = new org.mybatis.spring.SqlSessionTemplate(sqlSessions).getMapper(RefundMoneyRepository.class);
        org.mockito.Mockito.doAnswer(invocation -> {
                    reachedLedger.await(10, TimeUnit.SECONDS);
                    return realMoney.lockLedger(order);
                })
                .when(money)
                .lockLedger(order);
        var document = command(a);
        try (var pool = Executors.newFixedThreadPool(10)) {
            var deliveries = new ArrayList<Future<RefundAcceptanceService.Receipt>>();
            for (int i = 0; i < 10; i++) {
                deliveries.add(
                        pool.submit(() -> acceptance.accept(UUID.randomUUID().toString(), document)));
            }
            var receipts = new ArrayList<RefundAcceptanceService.Receipt>();
            for (var delivery : deliveries) receipts.add(delivery.get(20, TimeUnit.SECONDS));
            assertThat(receipts).filteredOn(receipt -> !receipt.replayed()).hasSize(1);
            assertThat(receipts)
                    .extracting(receipt -> receipt.operation().operationId())
                    .containsOnly(document.get("operation_id").stringValue());
            ledger(0, 32900);
            assertThat(jdbc.queryForObject("SELECT COUNT(*) FROM refund_operation WHERE line_id=?", Long.class, a))
                    .isEqualTo(1);
        }
    }

    @Test
    void concurrentLinesAndRepeatedSettlementsMoveMoneyAndEmitResultsOnce() throws Exception {
        try (var pool = Executors.newFixedThreadPool(8)) {
            var start = new CountDownLatch(1);
            var commands = List.of(command(a), command(b));
            var accepted = new ArrayList<Future<String>>();
            for (var n : commands)
                accepted.add(pool.submit(() -> {
                    start.await();
                    return acceptance
                            .accept(UUID.randomUUID().toString(), n)
                            .operation()
                            .operationId();
                }));
            start.countDown();
            var operations = new ArrayList<String>();
            for (var f : accepted) operations.add(f.get(15, TimeUnit.SECONDS));
            ledger(0, 72700);
            var settlements = new ArrayList<Future<?>>();
            for (int i = 0; i < 16; i++) {
                var op = operations.get(i % 2);
                settlements.add(pool.submit(() -> settlement.settleSucceeded(op, "synthetic-ok")));
            }
            for (var f : settlements) f.get(15, TimeUnit.SECONDS);
            ledger(72700, 0);
            assertThat(jdbc.queryForObject(
                            "SELECT COUNT(*) FROM event_outbox WHERE merchant_id=?", Long.class, merchant))
                    .isEqualTo(2);
            assertThat(jdbc.queryForList("SELECT state FROM line_refund WHERE line_id IN(?,?)", String.class, a, b))
                    .containsOnly("CONSUMED");
        }
    }

    @Test
    void aggregateCapRejectsTheOtherLineWithoutLeavingAPartialReservation() {
        jdbc.update("UPDATE payment_ledger SET paid_amount=39800 WHERE order_id=?", order);
        accept(b);
        ledger(0, 39800);
        assertThatThrownBy(() -> accept(a)).isInstanceOf(RefundRejectedException.class);
        ledger(0, 39800);
        assertThat(statuses.findRefundStatus(a).state()).isEqualTo("FREE");
        assertThat(jdbc.queryForObject(
                        "SELECT COUNT(*) FROM refund_operation WHERE merchant_id=?", Long.class, merchant))
                .isEqualTo(1);
    }
}
