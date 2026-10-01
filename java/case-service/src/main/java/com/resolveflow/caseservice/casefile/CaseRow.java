package com.resolveflow.caseservice.casefile;

import java.time.Instant;

/**
 * The persisted case row, exactly as {@code aftersale_case} holds it.
 *
 * <p>Requested actions live in their own table, so they are read separately when a view needs them;
 * keeping them out of this record keeps the row mapping a straight constructor mapping.
 */
public record CaseRow(
        String caseId,
        String merchantId,
        String customerId,
        String orderId,
        String lineId,
        /**
         * The customer's own words (V16__case_description.sql). The run dispatch carries them to the
         * Agent: the model is asked about the customer's problem, and a dispatch that left this blank
         * would start an investigation of nothing.
         */
        String description,
        CaseStatus status,
        int inputRevision,
        long version,
        Instant expiresAt,
        Instant createdAt,
        Instant updatedAt) {

    /**
     * Whether this case is the principal's to see or act on.
     *
     * <p>The rule lives here rather than in each service because it is one rule: the customer's own case, or
     * anything under the merchant the principal belongs to. Reading, cancelling and deciding all ask the same
     * question, and three copies of it would eventually disagree — the one that drifted would be a way to
     * reach somebody else's case. A case the caller cannot see is answered like one that does not exist, so
     * this returning false is a 404, not a 403 (docs/core-contracts.md:27).
     */
    public boolean visibleTo(com.resolveflow.shared.security.AuthenticatedPrincipal principal) {
        if (!merchantId.equals(principal.merchantId())) {
            return false;
        }
        return principal.role().isMerchantStaff() || customerId.equals(principal.customerId());
    }
}
