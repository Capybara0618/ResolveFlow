package com.resolveflow.shared.support;

import com.fasterxml.jackson.annotation.JsonProperty;
import java.time.Instant;

/** Customer-confirmed refund input; no browser supplied amount, tenant or case id. */
public final class SupportRefundWire {
    private SupportRefundWire() {}

    public record Prepare(@JsonProperty("expected_version") Long expectedVersion, String reason) {}

    public record Edit(Long revision, String reason) {}

    public record Revision(Long revision) {}

    public record Confirm(
            Long revision, @JsonProperty("expected_version") Long expectedVersion) {}

    public record Draft(
            @JsonProperty("draft_id") String draftId,
            long revision,
            @JsonProperty("expected_version") long expectedVersion,
            String status,
            String reason,
            int quantity,
            @JsonProperty("amount_minor") long amountMinor,
            String currency,
            @JsonProperty("expires_at") Instant expiresAt,
            @JsonProperty("case_id") String caseId) {}
}
