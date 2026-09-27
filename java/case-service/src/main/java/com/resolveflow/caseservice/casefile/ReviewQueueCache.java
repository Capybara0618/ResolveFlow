package com.resolveflow.caseservice.casefile;

import java.util.Optional;

/** A short-lived, non-authoritative copy of the merchant's review queue page. */
public interface ReviewQueueCache {

    Optional<ReviewQueueService.Page> find(String merchantId, String cursor, int limit);

    void store(String merchantId, String cursor, int limit, ReviewQueueService.Page page);
}
