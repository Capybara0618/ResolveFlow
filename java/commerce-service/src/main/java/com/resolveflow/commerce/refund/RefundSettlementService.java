package com.resolveflow.commerce.refund;

import com.resolveflow.commerce.messaging.ResultEventOutbox;
import java.time.Clock;
import java.time.Instant;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

/**
 * Settling a reserved refund, once the provider has actually answered
 * (docs/domain-model.md:49).
 *
 * <p>Each settlement is one transaction with three writes that must agree: the operation's terminal state,
 * the ledger's amounts, and the line's slot. Splitting them would allow a state where the money says
 * refunded and the line still says held — and that is the state a second refund would slip through.
 *
 * <p>Re-entry is the property that matters most here. Both methods are written so that a settlement arriving
 * twice — a provider callback retried, a retry loop that ran twice, a reconciliation that repeats — moves
 * money exactly once:
 *
 * <ul>
 *   <li>an operation that is already terminal is returned as it stands, without touching the ledger;
 *   <li>the state transition itself carries {@code state IN (…non-terminal…)} in its {@code WHERE}, so even
 *       two settlements in flight at once cannot both match;
 *   <li>and the ledger statements carry the amount conditions, so a settlement whose reservation has already
 *       been consumed matches no row.
 * </ul>
 *
 * <p>What this service deliberately does not do: it does not call the provider (C04.3). What it does do, as of
 * C05.2b, is write the result event the case is owed — in the same transaction as the settlement, because
 * "inbox、业务结果和本地事件同事务" is exactly this, and a settlement that committed without its event would leave
 * the case waiting for an outcome this service had already decided. Delivering that row is still somebody else's
 * transaction (the result publisher), which is why no network call appears in this class.
 */
@Service
public class RefundSettlementService {

    private final RefundOperationRepository operations;
    private final RefundMoneyRepository money;
    private final ResultEventOutbox results;
    private final Clock clock;

    public RefundSettlementService(
            RefundOperationRepository operations, RefundMoneyRepository money, ResultEventOutbox results, Clock clock) {
        this.operations = operations;
        this.money = money;
        this.results = results;
        this.clock = clock;
    }

    /**
     * The money is gone: the reservation becomes a refund, and the line can never be refunded again.
     *
     * <p>A settlement arriving twice moves money once and announces it once: the terminal operation is returned
     * as it stands, without touching the ledger and without writing a second result event. The case orders what
     * it receives by {@code aggregate_version}, but the cheapest duplicate is the one never sent.
     *
     * @return the stored operation after settlement
     */
    @Transactional
    public RefundOperationRepository.StoredOperation settleSucceeded(String operationId, String providerRef) {
        RefundOperationRepository.StoredOperation operation = lockedOperation(operationId);
        if (isTerminal(operation.state())) {
            return operation;
        }
        Instant now = Instant.now(clock);
        if (operations.settleSucceeded(operationId, providerRef, now) != 1) {
            throw new IllegalStateException("operation " + operationId + " changed while it was being settled");
        }
        if (money.consumeReservation(orderId(operation), operation.amountMinor()) != 1) {
            // The reservation this settlement means to spend is not on the ledger: a settlement that kept
            // going here would record money as refunded that the ledger never held.
            throw new IllegalStateException("operation " + operationId + " has no reservation left to consume");
        }
        if (money.consumeSlot(operation.lineId(), operationId, now) != 1) {
            throw new IllegalStateException("line " + operation.lineId() + " is not held by operation " + operationId);
        }
        return announce(require(operationId));
    }

    /**
     * The provider refused for a reason that will not change: the reservation is released and the line is
     * free again, which is the only way a line may be re-applied for
     * (docs/domain-model.md:51 — a new application only after a determined failure released the money).
     *
     * <p>The operation row is kept, not deleted: "this key failed and the money was released" is the fact the
     * next reader needs, and a deleted row could be replayed into a second reservation
     * (docs/domain-model.md:47, 确定失败后的旧ID也不可重新占用).
     */
    @Transactional
    public RefundOperationRepository.StoredOperation settleFailed(String operationId, String reasonCode) {
        RefundOperationRepository.StoredOperation operation = lockedOperation(operationId);
        if (isTerminal(operation.state())) {
            return operation;
        }
        Instant now = Instant.now(clock);
        if (operations.settleFailed(operationId, reasonCode, now) != 1) {
            throw new IllegalStateException("operation " + operationId + " changed while it was being settled");
        }
        if (money.releaseReservation(orderId(operation), operation.amountMinor()) != 1) {
            throw new IllegalStateException("operation " + operationId + " has no reservation left to release");
        }
        if (money.releaseSlot(operation.lineId(), operationId, now) != 1) {
            throw new IllegalStateException("line " + operation.lineId() + " is not held by operation " + operationId);
        }
        return announce(require(operationId));
    }

    /**
     * Nothing has been decided: the operation is recorded as {@code UNKNOWN}, the money stays reserved, and the
     * case is told (docs/domain-model.md:15, 51).
     *
     * <p>This is a settlement method rather than a call straight to the repository (C05.2b) because the
     * transition and the event it owes must share a transaction, exactly as the two terminal ones do. The
     * dispatch path used to call {@code operations.markUnknown} directly, which would have left the case with no
     * way to learn that an attempt produced no answer.
     *
     * <p><b>A repeat writes nothing.</b> {@code markUnknown} only matches an operation that is
     * {@code RECEIVED} or {@code IN_PROGRESS}, so a second unknown attempt on an operation that is already
     * {@code UNKNOWN} changes no fact: the case was told when it first went unknown, the version has not moved,
     * and re-notifying the same version would be the duplicate that {@code aggregate_version} exists to expose.
     * A later attempt that succeeds or is refused still sends its own event, with a higher version.
     */
    @Transactional
    public RefundOperationRepository.StoredOperation settleUnknown(
            String operationId, String reasonCode, Instant retryAt) {
        RefundOperationRepository.StoredOperation operation = lockedOperation(operationId);
        if (isTerminal(operation.state())) {
            return operation;
        }
        if (operations.markUnknown(operationId, reasonCode, retryAt) != 1) {
            return require(operationId);
        }
        return announce(require(operationId));
    }

    /**
     * Write the result event this operation's new state owes the case, and return the stored operation.
     *
     * <p>Every path that changes an operation's state calls this, and the event is written inside the
     * settlement's own transaction: the case may learn that a refund succeeded only if the ledger really moved,
     * and it may not be left uninformed about a settlement that committed.
     */
    private RefundOperationRepository.StoredOperation announce(RefundOperationRepository.StoredOperation operation) {
        results.writeRefundResult(operation);
        return operation;
    }

    private RefundOperationRepository.StoredOperation require(String operationId) {
        RefundOperationRepository.StoredOperation operation = operations.find(operationId);
        if (operation == null) {
            throw new IllegalArgumentException("no refund operation " + operationId);
        }
        return operation;
    }

    private RefundOperationRepository.StoredOperation lockedOperation(String id) {
        var observed = require(id);
        if (isTerminal(observed.state())) return observed;
        if (money.lockLedger(orderId(observed)) == null) throw new IllegalStateException("missing refund ledger");
        // A locking current read, not the earlier REPEATABLE READ snapshot: another settlement may
        // have committed while this transaction waited for the shared order ledger.
        var current = operations.findForUpdate(id);
        if (current == null) throw new IllegalStateException("missing refund operation");
        return current;
    }

    private static boolean isTerminal(String state) {
        return "SUCCEEDED".equals(state) || "FAILED".equals(state);
    }

    /** The order whose ledger this operation reserved against, read from the line it names. */
    private String orderId(RefundOperationRepository.StoredOperation operation) {
        String orderId = operations.findOrderId(operation.operationId());
        if (orderId == null) {
            throw new IllegalStateException("operation " + operation.operationId() + " names a line that is gone");
        }
        return orderId;
    }
}
