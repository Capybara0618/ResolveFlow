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
        CaseStatus status,
        int inputRevision,
        long version,
        Instant expiresAt,
        Instant createdAt,
        Instant updatedAt) {}
