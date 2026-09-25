package com.resolveflow.commerce.refund;

import com.resolveflow.commerce.order.LineRefundStatusRepository;
import java.util.Optional;
import org.springframework.stereotype.Service;

/**
 * The read behind {@code GET /internal/v1/order-lines/{line_id}/refund-status} (C06.2c).
 *
 * <p>Thin, and deliberately so: what this route reports is already decided by two tables, and the only decisions
 * left are the two this class makes — that a line without a refund slot is **not** an answer, and that the
 * refundable amount is not computed here.
 *
 * <p>Nothing here enforces scope. The route is service-token only, and scope is the caller's: Case derives it from
 * the verified user token, and the Agent reads it for the line the run is about. A second opinion here would be
 * the one that drifts (the same division as the line-context and shipment reads).
 */
@Service
public class RefundStatusReadService {

    private final LineRefundStatusRepository repository;

    public RefundStatusReadService(LineRefundStatusRepository repository) {
        this.repository = repository;
    }

    /**
     * One line's refund status, or empty when there is no such line **or** no slot for it.
     *
     * <p>The two cases answer the same 404, and that is intentional rather than lazy. The contract's {@code state}
     * is required with no "unknown" member, so a slot-less line cannot be described; and the honest thing to say
     * about a line whose refund state cannot be determined is that this route has no answer. Returning
     * {@code FREE} — the tempting default — would assert that nothing has ever been reserved on it, which is a
     * claim about money that nothing observed. `docs/agent-spec.md:36` says NOT_FOUND is not a negative fact, and
     * this is that rule applied to a required member that has no honest value.
     */
    public Optional<LineRefundStatusRepository.LineRefundStatusRow> readRefundStatus(String lineId) {
        if (lineId == null || lineId.isBlank()) {
            throw new IllegalArgumentException("a refund-status read needs a line id");
        }
        LineRefundStatusRepository.LineRefundStatusRow row = repository.findRefundStatus(lineId);
        if (row == null || row.state() == null) {
            return Optional.empty();
        }
        return Optional.of(row);
    }
}
