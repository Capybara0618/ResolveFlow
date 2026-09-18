package com.resolveflow.spike.entitlement;

/** Row projections. Records per docs/engineering.md. */
public final class EntitlementRows {

    private EntitlementRows() {
    }

    public record EntitlementRow(long lineId, long merchantId, String action,
                                 String operationId, String state, long version) {
    }

    public record LedgerRow(long orderId, long paidAmount, long refundedAmount,
                            long reservedRefundAmount, long version) {
    }
}