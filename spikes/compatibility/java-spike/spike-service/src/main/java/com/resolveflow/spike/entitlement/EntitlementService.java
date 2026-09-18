package com.resolveflow.spike.entitlement;

import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.util.Optional;

import static com.resolveflow.spike.entitlement.EntitlementRows.EntitlementRow;
import static com.resolveflow.spike.entitlement.EntitlementRows.LedgerRow;

/**
 * Spike-sized version of the commerce line-entitlement transaction.
 *
 * <p>Shape follows docs/engineering.md (row lock, conditional UPDATE, affected-row
 * count decides) and docs/domain-model.md: refund and reship share one line row so
 * they are mutually exclusive; a repeated operation returns its original result; a
 * different operation on an occupied line is a conflict; a reservation that would
 * exceed the paid amount is a business rejection, not an error.
 */
@Service
public class EntitlementService {

    private final EntitlementMapper mapper;

    public EntitlementService(EntitlementMapper mapper) {
        this.mapper = mapper;
    }

    /** Raised when the request is understood but must not proceed (e.g. insufficient balance). */
    public static class BusinessRejectException extends RuntimeException {
        public BusinessRejectException(String message) {
            super(message);
        }
    }

    /** Raised when another operation already holds the line. */
    public static class EntitlementConflictException extends RuntimeException {
        public EntitlementConflictException(String message) {
            super(message);
        }
    }

    public record ReserveResult(String operationId, long lineId, String action,
                                String state, long entitlementVersion) {
    }

    /**
     * Reserve the line for a refund. Locks the line first, so concurrent callers
     * serialise on the entitlement row rather than both passing a balance check.
     */
    @Transactional
    public ReserveResult reserveRefund(long lineId, long orderId, String operationId, long amount) {
        EntitlementRow entitlement = mapper.lockByLine(lineId)
                .orElseThrow(() -> new BusinessRejectException("unknown line " + lineId));

        // Same operation retried: return the original result, do not reserve twice.
        if (operationId.equals(entitlement.operationId())) {
            return new ReserveResult(operationId, lineId, entitlement.action(),
                    entitlement.state(), entitlement.version());
        }
        // INV-02: another operation already holds this line (refund or reship).
        if (!"FREE".equals(entitlement.state())) {
            throw new EntitlementConflictException(
                    "line " + lineId + " already held by operation " + entitlement.operationId()
                            + " in state " + entitlement.state());
        }

        LedgerRow ledger = mapper.lockLedger(orderId)
                .orElseThrow(() -> new BusinessRejectException("unknown order " + orderId));

        int ledgerRows = mapper.reserveRefundAmount(orderId, amount, ledger.version());
        if (ledgerRows == 0) {
            // Lost the conditional update: re-read rather than overwrite.
            LedgerRow current = mapper.lockLedger(orderId).orElseThrow();
            throw new BusinessRejectException(
                    "insufficient balance on order " + orderId
                            + ": paid=" + current.paidAmount()
                            + " refunded=" + current.refundedAmount()
                            + " reserved=" + current.reservedRefundAmount()
                            + " requested=" + amount);
        }

        int entitlementRows = mapper.occupyIfFree(lineId, "REFUND", operationId, entitlement.version());
        if (entitlementRows == 0) {
            // Aborts the transaction, so the ledger reservation above rolls back with it.
            throw new EntitlementConflictException("line " + lineId + " changed under us; retry");
        }
        mapper.recordOperation(operationId, lineId, "REFUND", "RESERVED");

        return new ReserveResult(operationId, lineId, "REFUND", "RESERVED", entitlement.version() + 1);
    }

    /** RESERVED -> IN_USE. Required before the target service may call the provider. */
    @Transactional
    public ReserveResult start(long lineId, String operationId) {
        EntitlementRow entitlement = mapper.lockByLine(lineId).orElseThrow();
        int rows = mapper.startIfReserved(lineId, operationId, entitlement.version());
        if (rows == 0) {
            throw new EntitlementConflictException(
                    "line " + lineId + " is " + entitlement.state() + ", cannot start " + operationId);
        }
        return new ReserveResult(operationId, lineId, entitlement.action(), "IN_USE", entitlement.version() + 1);
    }

    /** Success: consume the entitlement and turn the reserved money into refunded money. */
    @Transactional
    public ReserveResult commitRefund(long lineId, long orderId, String operationId, long amount) {
        EntitlementRow entitlement = mapper.lockByLine(lineId).orElseThrow();
        LedgerRow ledger = mapper.lockLedger(orderId).orElseThrow();

        int entitlementRows = mapper.consumeIfInUse(lineId, operationId, entitlement.version());
        if (entitlementRows == 0) {
            throw new EntitlementConflictException(
                    "line " + lineId + " not IN_USE for " + operationId + " (state " + entitlement.state() + ")");
        }
        int ledgerRows = mapper.settleRefund(orderId, amount, ledger.version());
        if (ledgerRows == 0) {
            throw new IllegalStateException("ledger settle failed for order " + orderId);
        }
        return new ReserveResult(operationId, lineId, "REFUND", "CONSUMED", entitlement.version() + 1);
    }

    /** Observation only; deliberately non-locking so it is safe in a read-only transaction. */
    @Transactional(readOnly = true)
    public Optional<EntitlementRow> findLine(long lineId) {
        return mapper.selectLine(lineId);
    }

    @Transactional(readOnly = true)
    public Optional<LedgerRow> findLedger(long orderId) {
        return mapper.selectLedger(orderId);
    }
}