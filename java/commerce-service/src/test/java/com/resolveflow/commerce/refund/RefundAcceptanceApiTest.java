package com.resolveflow.commerce.refund;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

import com.resolveflow.commerce.CommerceDatabaseTest;
import com.resolveflow.shared.contract.CanonicalJson;
import java.util.ArrayList;
import java.util.List;
import java.util.UUID;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicInteger;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.jdbc.core.JdbcTemplate;
import tools.jackson.databind.ObjectMapper;
import tools.jackson.databind.node.ObjectNode;

/**
 * Accepting and settling a refund command (C04.2, docs/domain-model.md:47,49).
 *
 * <p>The properties under test are the ones that decide whether money can move twice:
 *
 * <ul>
 *   <li><b>The same command twice reserves once.</b> A redelivery is answered from the operation record;
 *       a known id with a different payload is refused, because the hash is what the authorisation fixed.
 *   <li><b>One live refund per line, enforced by the database.</b> A consumed line never refunds again; a
 *       held line belongs to whoever holds it; and under 100 concurrent commands for the same line exactly
 *       one reservation survives.
 *   <li><b>The ledger is the money truth.</b> Reserving moves {@code reserved_refund_amount} only, a
 *       success moves it into {@code refunded_amount}, and a determined failure releases it — never leaving
 *       the order accounting for more than it was paid.
 *   <li><b>Settlement is idempotent.</b> Settling the same operation twice moves the money once, which is
 *       the whole reason the state transition carries its expected state in the {@code WHERE}.
 * </ul>
 *
 * <p>These run on real MySQL through the real migrations: every guarantee here is a database guarantee
 * (CHECK constraints, the generated-column unique key, row locks), and an in-memory stand-in would not
 * enforce the ones that matter.
 */
class RefundAcceptanceApiTest extends CommerceDatabaseTest {

    private static final ObjectMapper MAPPER = new ObjectMapper();
    private static final String MERCHANT = "M-1001";

    /** Both lines belong to demo order ...00aa, paid 2599 and 1999 (V2__demo_order_seed.sql). */
    private static final String LINE_7001 = "7001";

    private static final String LINE_7002 = "7002";

    @Autowired
    RefundAcceptanceService acceptance;

    @Autowired
    RefundSettlementService settlement;

    @Autowired
    RefundOperationRepository operations;

    @Autowired
    JdbcTemplate jdbc;

    @BeforeEach
    void resetMoneyState() {
        // Only the refund path's own tables are cleared; the order read model and its seed are the fixture
        // these tests are about, and deleting them would delete the world under test.
        jdbc.execute("DELETE FROM refund_request_inbox");
        jdbc.execute("DELETE FROM refund_operation");
        jdbc.execute("UPDATE line_refund SET state = 'FREE', operation_id = NULL, version = 1");
        jdbc.execute("UPDATE payment_ledger SET refunded_amount = 0, reserved_refund_amount = 0, version = 1");
    }

    /**
     * A command document, minted once per operation id.
     *
     * <p>The cache is not convenience: a redelivery has to carry the *same* document, and a helper that
     * minted fresh case and authorisation ids on every call would make two calls two different commands
     * sharing an operation id — which is the case this test class means to refuse, not to exercise.
     */
    private final java.util.Map<String, ObjectNode> minted = new java.util.concurrent.ConcurrentHashMap<>();

    private ObjectNode command(String operationId, String lineId, long amountMinor, int quantity, String merchant) {
        String key = operationId + "/" + lineId + "/" + amountMinor + "/" + quantity + "/" + merchant;
        return minted.computeIfAbsent(key, ignored -> mint(operationId, lineId, amountMinor, quantity, merchant))
                .deepCopy();
    }

    private ObjectNode mint(String operationId, String lineId, long amountMinor, int quantity, String merchant) {
        ObjectNode node = MAPPER.createObjectNode();
        node.put("operation_id", operationId);
        node.put("case_id", UUID.randomUUID().toString());
        node.put("authorization_id", UUID.randomUUID().toString());
        node.put("input_revision", 2);
        node.put("line_id", lineId);
        node.put("merchant_id", merchant);
        node.put("action", "REFUND");
        node.put("quantity", quantity);
        node.put("currency", "CNY");
        node.put("amount_minor", amountMinor);
        node.put("policy_version", "2026.09");
        node.put("target_service", "commerce-service");
        node.put("payload_hash", CanonicalJson.payloadHash(nodeWithoutHash(node)));
        return node;
    }

    /** The twelve hashed members, in the shape the hash covers. */
    private static ObjectNode nodeWithoutHash(ObjectNode document) {
        ObjectNode copy = document.deepCopy();
        copy.remove("payload_hash");
        return copy;
    }

    private ObjectNode fullLineCommand(String operationId) {
        return command(operationId, LINE_7001, 2599, 2, MERCHANT);
    }

    private long refunded(String orderId) {
        return jdbc.queryForObject(
                "SELECT refunded_amount FROM payment_ledger WHERE order_id = ?", Long.class, orderId);
    }

    private long reserved(String orderId) {
        return jdbc.queryForObject(
                "SELECT reserved_refund_amount FROM payment_ledger WHERE order_id = ?", Long.class, orderId);
    }

    private String orderIdOf(String lineId) {
        return jdbc.queryForObject("SELECT order_id FROM order_line WHERE line_id = ?", String.class, lineId);
    }

    private String slotState(String lineId) {
        return jdbc.queryForObject("SELECT state FROM line_refund WHERE line_id = ?", String.class, lineId);
    }

    @Test
    @DisplayName("a command reserves the line and the money, and the operation says so")
    void acceptingReservesTheLineAndTheMoney() {
        RefundAcceptanceService.Receipt receipt = acceptance.accept("req-1", fullLineCommand("op-1"));

        assertThat(receipt.replayed()).isFalse();
        assertThat(receipt.operation().state()).isEqualTo("RECEIVED");
        assertThat(receipt.operation().providerKey())
                .as("the provider's key is the operation id, fixed before the provider is ever called")
                .isEqualTo("op-1");
        assertThat(receipt.operation().providerRef()).isNull();
        assertThat(receipt.operation().settledAt()).isNull();
        assertThat(slotState(LINE_7001)).isEqualTo("RESERVED");
        assertThat(reserved(orderIdOf(LINE_7001))).isEqualTo(2599);
        assertThat(refunded(orderIdOf(LINE_7001)))
                .as("reserving is not refunding: no money has moved yet")
                .isZero();
    }

    @Test
    @DisplayName("the same command twice reserves once and answers with the stored operation")
    void aRedeliveryIsAnsweredFromTheRecord() {
        RefundAcceptanceService.Receipt first = acceptance.accept("req-1", fullLineCommand("op-1"));
        RefundAcceptanceService.Receipt second = acceptance.accept("req-2", fullLineCommand("op-1"));

        assertThat(second.replayed()).isTrue();
        assertThat(second.operation()).isEqualTo(first.operation());
        assertThat(reserved(orderIdOf(LINE_7001))).isEqualTo(2599);
        assertThat(jdbc.queryForObject("SELECT COUNT(*) FROM refund_operation", Integer.class))
                .isEqualTo(1);
    }

    @Test
    @DisplayName("the same operation id with a different payload is refused and changes nothing")
    void aChangedPayloadUnderOneIdIsRefused() {
        acceptance.accept("req-1", fullLineCommand("op-1"));

        ObjectNode different = command("op-1", LINE_7002, 1999, 1, MERCHANT);

        assertThatThrownBy(() -> acceptance.accept("req-2", different))
                .isInstanceOf(RefundRejectedException.class)
                .satisfies(error -> assertThat(((RefundRejectedException) error).error())
                        .isEqualTo(RefundError.PAYLOAD_HASH_MISMATCH));
        // The refused command touches nothing: its own line is still free, and the ledger has not gained a
        // second reservation. (The two demo lines share one order, so the ledger figure cannot be asserted as
        // zero here — the first command's reservation is legitimately on it.)
        assertThat(slotState(LINE_7002)).isEqualTo("FREE");
        assertThat(reserved(orderIdOf(LINE_7001)))
                .as("still exactly the first command's reservation")
                .isEqualTo(2599);
    }

    @Test
    @DisplayName("a command whose payload_hash does not cover its members is refused before anything is written")
    void aTamperedHashIsRefused() {
        ObjectNode tampered = fullLineCommand("op-1");
        tampered.put("amount_minor", 1);

        assertThatThrownBy(() -> acceptance.accept("req-1", tampered))
                .isInstanceOf(RefundRejectedException.class)
                .satisfies(error -> assertThat(((RefundRejectedException) error).error())
                        .isEqualTo(RefundError.PAYLOAD_HASH_MISMATCH));
        assertThat(jdbc.queryForObject("SELECT COUNT(*) FROM refund_operation", Integer.class))
                .isZero();
        assertThat(reserved(orderIdOf(LINE_7001))).isZero();
    }

    @Test
    @DisplayName("an amount that is not the line's own is refused: a core refund is not a partial one")
    void anAmountThatIsNotTheLinesOwnIsRefused() {
        ObjectNode smaller = command("op-1", LINE_7001, 100, 2, MERCHANT);

        assertThatThrownBy(() -> acceptance.accept("req-1", smaller))
                .isInstanceOf(RefundRejectedException.class)
                .satisfies(error ->
                        assertThat(((RefundRejectedException) error).error()).isEqualTo(RefundError.AMOUNT_MISMATCH));
        assertThat(slotState(LINE_7001)).isEqualTo("FREE");
    }

    @Test
    @DisplayName("a line belonging to another merchant is refused")
    void anotherMerchantsLineIsRefused() {
        ObjectNode otherMerchant = command("op-1", LINE_7001, 2599, 2, "M-1002");

        assertThatThrownBy(() -> acceptance.accept("req-1", otherMerchant))
                .isInstanceOf(RefundRejectedException.class)
                .satisfies(error -> assertThat(((RefundRejectedException) error).error())
                        .isEqualTo(RefundError.LINE_OWNER_MISMATCH));
        assertThat(slotState(LINE_7001)).isEqualTo("FREE");
    }

    @Test
    @DisplayName("a line that does not exist is a refusal, not an empty reservation")
    void anUnknownLineIsRefused() {
        ObjectNode unknown = command("op-1", "9999", 2599, 2, MERCHANT);

        assertThatThrownBy(() -> acceptance.accept("req-1", unknown))
                .isInstanceOf(RefundRejectedException.class)
                .satisfies(error ->
                        assertThat(((RefundRejectedException) error).error()).isEqualTo(RefundError.LINE_NOT_FOUND));
        assertThat(jdbc.queryForObject("SELECT COUNT(*) FROM refund_operation", Integer.class))
                .isZero();
    }

    @Test
    @DisplayName("a reserved line cannot be taken by a second operation")
    void aHeldLineIsNotAvailable() {
        acceptance.accept("req-1", fullLineCommand("op-1"));

        ObjectNode second = command("op-2", LINE_7001, 2599, 2, MERCHANT);

        assertThatThrownBy(() -> acceptance.accept("req-2", second))
                .isInstanceOf(RefundRejectedException.class)
                .satisfies(error -> assertThat(((RefundRejectedException) error).error())
                        .isEqualTo(RefundError.ANOTHER_OPERATION_LIVE));
        assertThat(reserved(orderIdOf(LINE_7001))).isEqualTo(2599);
    }

    @Test
    @DisplayName("exactly one command wins the line, under real contention")
    void manyConcurrentCommandsForOneLineReserveOnce() throws Exception {
        int commands = 100;
        ExecutorService pool = Executors.newFixedThreadPool(16);
        CountDownLatch start = new CountDownLatch(1);
        CountDownLatch done = new CountDownLatch(commands);
        AtomicInteger accepted = new AtomicInteger();
        AtomicInteger lostTheRace = new AtomicInteger();
        List<Throwable> unexpected = new ArrayList<>();

        try {
            for (int i = 0; i < commands; i++) {
                String operationId = "op-concurrent-" + i;
                pool.submit(() -> {
                    try {
                        start.await();
                        acceptance.accept("req-concurrent-" + UUID.randomUUID(), fullLineCommand(operationId));
                        accepted.incrementAndGet();
                    } catch (RefundRejectedException rejected) {
                        lostTheRace.incrementAndGet();
                    } catch (Throwable other) {
                        // A losing writer can also meet the database's own refusal (a deadlock or a lock
                        // timeout) instead of a check: both mean "this command reserved nothing", and the
                        // property under test is what survived, not which exception the loser saw. Anything
                        // else is a bug and fails the test below.
                        synchronized (unexpected) {
                            unexpected.add(other);
                        }
                    } finally {
                        done.countDown();
                    }
                });
            }
            start.countDown();
            assertThat(done.await(120, TimeUnit.SECONDS))
                    .as("the commands finished")
                    .isTrue();
        } finally {
            pool.shutdownNow();
        }

        assertThat(unexpected)
                .as("no command failed for a reason other than losing the line")
                .allSatisfy(error -> assertThat(error)
                        .isInstanceOfAny(
                                org.springframework.dao.ConcurrencyFailureException.class,
                                org.springframework.dao.CannotAcquireLockException.class,
                                org.springframework.dao.DeadlockLoserDataAccessException.class));
        assertThat(accepted.get()).as("exactly one command may hold the line").isEqualTo(1);
        assertThat(lostTheRace.get() + accepted.get()).isEqualTo(commands);
        assertThat(reserved(orderIdOf(LINE_7001)))
                .as("100 attempts to reserve 2599 on one line leave exactly one reservation")
                .isEqualTo(2599);
        assertThat(jdbc.queryForObject(
                        "SELECT COUNT(*) FROM refund_operation WHERE state IN ('RECEIVED','IN_PROGRESS')",
                        Integer.class))
                .as("and exactly one live operation exists")
                .isEqualTo(1);
    }

    @Test
    @DisplayName("settling a success moves the reservation into refunded money and consumes the line")
    void settlingASuccessMovesTheMoney() {
        acceptance.accept("req-1", fullLineCommand("op-1"));

        RefundOperationRepository.StoredOperation settled = settlement.settleSucceeded("op-1", "prv-1111");

        assertThat(settled.state()).isEqualTo("SUCCEEDED");
        assertThat(settled.providerRef()).isEqualTo("prv-1111");
        assertThat(settled.settledAt()).isNotNull();
        String orderId = orderIdOf(LINE_7001);
        assertThat(refunded(orderId)).isEqualTo(2599);
        assertThat(reserved(orderId)).isZero();
        assertThat(slotState(LINE_7001)).isEqualTo("CONSUMED");
    }

    @Test
    @DisplayName("settling the same success twice moves the money once")
    void settlingTwiceMovesMoneyOnce() {
        acceptance.accept("req-1", fullLineCommand("op-1"));
        settlement.settleSucceeded("op-1", "prv-1111");

        RefundOperationRepository.StoredOperation again = settlement.settleSucceeded("op-1", "prv-1111");

        assertThat(again.state()).isEqualTo("SUCCEEDED");
        assertThat(refunded(orderIdOf(LINE_7001))).isEqualTo(2599);
        assertThat(reserved(orderIdOf(LINE_7001))).isZero();
    }

    @Test
    @DisplayName("a refunded line can never be refunded again, even by a new operation")
    void aRefundedLineIsFinished() {
        acceptance.accept("req-1", fullLineCommand("op-1"));
        settlement.settleSucceeded("op-1", "prv-1111");

        ObjectNode second = command("op-2", LINE_7001, 2599, 2, MERCHANT);

        assertThatThrownBy(() -> acceptance.accept("req-2", second))
                .isInstanceOf(RefundRejectedException.class)
                .satisfies(error ->
                        assertThat(((RefundRejectedException) error).error()).isEqualTo(RefundError.ALREADY_REFUNDED));
        assertThat(refunded(orderIdOf(LINE_7001))).isEqualTo(2599);
    }

    @Test
    @DisplayName("a determined failure releases the money and frees the line, keeping the failed command")
    void aDeterminedFailureReleasesTheLine() {
        acceptance.accept("req-1", fullLineCommand("op-1"));

        RefundOperationRepository.StoredOperation failed = settlement.settleFailed("op-1", "DECLINED");

        assertThat(failed.state()).isEqualTo("FAILED");
        assertThat(failed.reasonCode()).isEqualTo("DECLINED");
        String orderId = orderIdOf(LINE_7001);
        assertThat(reserved(orderId)).isZero();
        assertThat(refunded(orderId)).isZero();
        assertThat(slotState(LINE_7001)).isEqualTo("FREE");
        assertThat(jdbc.queryForObject(
                        "SELECT COUNT(*) FROM refund_operation WHERE operation_id = 'op-1'", Integer.class))
                .as("the failed command is kept: it is why the money was released")
                .isEqualTo(1);
    }

    @Test
    @DisplayName("a second command reusing the failed operation id is answered, not re-executed")
    void aFailedOperationIdIsNeverReused() {
        acceptance.accept("req-1", fullLineCommand("op-1"));
        settlement.settleFailed("op-1", "DECLINED");

        RefundAcceptanceService.Receipt again = acceptance.accept("req-1b", fullLineCommand("op-1"));

        assertThat(again.replayed()).isTrue();
        assertThat(again.operation().state()).isEqualTo("FAILED");
        assertThat(reserved(orderIdOf(LINE_7001)))
                .as("a replayed failure must not reserve the money again")
                .isZero();
        assertThat(slotState(LINE_7001)).isEqualTo("FREE");
    }

    @Test
    @DisplayName("after a failure released the line, a new operation may apply for it")
    void aReleasedLineCanBeAppliedForAgain() {
        acceptance.accept("req-1", fullLineCommand("op-1"));
        settlement.settleFailed("op-1", "DECLINED");

        RefundAcceptanceService.Receipt second = acceptance.accept("req-2", fullLineCommand("op-2"));

        assertThat(second.replayed()).isFalse();
        assertThat(second.operation().state()).isEqualTo("RECEIVED");
        assertThat(slotState(LINE_7001)).isEqualTo("RESERVED");
        assertThat(reserved(orderIdOf(LINE_7001))).isEqualTo(2599);
    }

    @Test
    @DisplayName("the ledger refuses a reservation the order cannot pay for")
    void theLedgerRefusesWhatTheOrderCannotPay() {
        // Both lines of order ...00aa belong to one order whose paid amount covers them; line 7001's refund
        // consumes its own price, and the ledger's constraint is what stops the order from accounting for
        // more than it was paid.
        jdbc.update("UPDATE payment_ledger SET paid_amount = 2599 WHERE order_id = ?", orderIdOf(LINE_7001));
        acceptance.accept("req-1", fullLineCommand("op-1"));
        settlement.settleSucceeded("op-1", "prv-1111");

        ObjectNode secondLine = command("op-2", LINE_7002, 1999, 1, MERCHANT);

        assertThatThrownBy(() -> acceptance.accept("req-2", secondLine))
                .isInstanceOf(RefundRejectedException.class)
                .satisfies(error ->
                        assertThat(((RefundRejectedException) error).error()).isEqualTo(RefundError.AMOUNT_MISMATCH));
        assertThat(refunded(orderIdOf(LINE_7001))).isEqualTo(2599);
        assertThat(reserved(orderIdOf(LINE_7002))).isZero();
    }

    @Test
    @DisplayName("a refund command for an unknown action is refused as a malformed command")
    void anUnknownActionIsRefused() {
        ObjectNode reship = fullLineCommand("op-1");
        reship.put("action", "RESHIP");
        // The hash is left as the REFUND hash on purpose: the action check must refuse this before anything
        // tries to canonicalise a RESHIP payload. (The canonicaliser would demand address_hash, which is the
        // compat-only field core deliberately does not have — that is a second, later line of defence.)
        assertThatThrownBy(() -> acceptance.accept("req-1", reship))
                .isInstanceOf(RefundRejectedException.class)
                .satisfies(error ->
                        assertThat(((RefundRejectedException) error).error()).isEqualTo(RefundError.MALFORMED_COMMAND));
        assertThat(jdbc.queryForObject("SELECT COUNT(*) FROM refund_operation", Integer.class))
                .isZero();
    }

    @Test
    @DisplayName("one delivery id reused for a different command is refused")
    void aDeliveryIdIsNotReusableForDifferentMoney() {
        acceptance.accept("req-1", fullLineCommand("op-1"));

        ObjectNode other = command("op-2", LINE_7002, 1999, 1, MERCHANT);

        assertThatThrownBy(() -> acceptance.accept("req-1", other))
                .isInstanceOf(RefundRejectedException.class)
                .satisfies(error ->
                        assertThat(((RefundRejectedException) error).error()).isEqualTo(RefundError.MALFORMED_COMMAND));
        assertThat(slotState(LINE_7002)).isEqualTo("FREE");
    }

    @Test
    @DisplayName("the operation list of a line is what the next reader needs, not a second money record")
    void operationsAreReadableByLine() {
        acceptance.accept("req-1", fullLineCommand("op-1"));
        settlement.settleFailed("op-1", "DECLINED");

        assertThat(operations.find("op-1").lineId()).isEqualTo(LINE_7001);
        assertThat(operations.findOrderId("op-1")).isEqualTo(orderIdOf(LINE_7001));
        assertThat(operations.find("op-1").reasonCode()).isEqualTo("DECLINED");
    }
}
