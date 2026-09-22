package com.resolveflow.commerce.refund;

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
 * <p>What this service deliberately does not do: it does not call the provider (C04.3), and it does not write
 * the result event (C05 owns outbox delivery). Both are other transactions' business, and a settlement that
 * reached the network would hold the line's lock for as long as the network took.
 */
@Service
public class RefundSettlementService {

    private final RefundOperationRepository operations;
    private final RefundMoneyRepository money;
    private final Clock clock;

    public RefundSettlementService(RefundOperationRepository operations, RefundMoneyRepository money, Clock clock) {
        this.operations = operations;
        this.money = money;
        this.clock = clock;
    }

    /**
     * The money is gone: the reservation becomes a refund, and the line can never be refunded again.
     *
     * @return the stored operation after settlement
     */
    @Transactional
    public RefundOperationRepository.StoredOperation settleSucceeded(String operationId, String providerRef) {
        RefundOperationRepository.StoredOperation operation = require(operationId);
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
        return require(operationId);
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
        RefundOperationRepository.StoredOperation operation = require(operationId);
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
        return require(operationId);
    }

    private RefundOperationRepository.StoredOperation require(String operationId) {
        RefundOperationRepository.StoredOperation operation = operations.find(operationId);
        if (operation == null) {
            throw new IllegalArgumentException("no refund operation " + operationId);
        }
        return operation;
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
