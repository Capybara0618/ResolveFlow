package com.resolveflow.caseservice.casefile;

import java.time.Instant;

/**
 * One row of the review queue, as the query returns it (C03.2c).
 *
 * <p>It carries exactly what {@code ReviewQueueItem} requires and nothing else: the queue is a filter over
 * case state, so a row that also carried the proposal or the evidence would be a second case view that
 * could disagree with the first.
 */
public record ReviewQueueRow(
        String caseId,
        String merchantId,
        String lineId,
        String status,
        int inputRevision,
        long version,
        Instant updatedAt) {

    public CaseStatus caseStatus() {
        return CaseStatus.of(status);
    }
}
