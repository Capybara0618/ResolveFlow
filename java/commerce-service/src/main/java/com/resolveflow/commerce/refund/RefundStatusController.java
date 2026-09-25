package com.resolveflow.commerce.refund;

import com.fasterxml.jackson.annotation.JsonInclude;
import com.fasterxml.jackson.annotation.JsonProperty;
import com.resolveflow.commerce.order.LineRefundStatusRepository;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

/**
 * {@code GET /internal/v1/order-lines/{line_id}/refund-status}: the refunded, reserved and current refund state
 * for one line (C06.2c, contracts/core/openapi-commerce.yaml:159).
 *
 * <p>The contract declared this route before anything served it, and C06.2b's {@code get_refund_status} tool had
 * nothing to read. It is the last of the three Commerce reads the five tools depend on.
 *
 * <p><b>{@code operation_id} is omitted when there is none.</b> The contract types it {@code ["string",
 * "null"]}, but the core wire says "absent" by omitting a member rather than by sending null
 * (docs/core-contracts.md:17, and {@code CoreWireModel.refuse_explicit_null} enforces the same rule on the Python
 * side). So a free line has no {@code operation_id} member at all, which is also the clearest statement of the
 * schema's own constraint: {@code state = 'FREE'} exactly when the operation is null.
 *
 * <p>Times and amounts are not recomputed here. Amounts are integer minor units in CNY taken from the row
 * (docs/core-contracts.md:17), and the refundable amount is not returned at all — see the service.
 */
@RestController
@RequestMapping("/internal/v1/order-lines")
public class RefundStatusController {

    private final RefundStatusReadService service;

    public RefundStatusController(RefundStatusReadService service) {
        this.service = service;
    }

    @GetMapping("/{line_id}/refund-status")
    public ResponseEntity<LineRefundStatusResponse> refundStatus(@PathVariable("line_id") String lineId) {
        return service.readRefundStatus(lineId)
                .map(LineRefundStatusResponse::from)
                .map(ResponseEntity::ok)
                .orElseThrow(() -> new RefundStatusNotFoundException(lineId));
    }

    /** The contract's {@code LineRefundStatus}, member for member. */
    @JsonInclude(JsonInclude.Include.NON_NULL)
    public record LineRefundStatusResponse(
            @JsonProperty("line_id") String lineId,
            @JsonProperty("merchant_id") String merchantId,
            @JsonProperty("line_paid_amount") long linePaidAmount,
            @JsonProperty("refunded_amount") long refundedAmount,
            @JsonProperty("reserved_refund_amount") long reservedRefundAmount,
            String currency,
            String state,
            @JsonProperty("operation_id") String operationId,
            long version) {

        static LineRefundStatusResponse from(LineRefundStatusRepository.LineRefundStatusRow row) {
            return new LineRefundStatusResponse(
                    row.lineId(),
                    row.merchantId(),
                    row.linePaidAmount(),
                    row.refundedAmount(),
                    row.reservedRefundAmount(),
                    row.currency(),
                    row.state(),
                    // Null on a free line, and NON_NULL drops it: the member is absent rather than null.
                    row.operationId(),
                    row.version());
        }
    }

    /**
     * No refund status for this line: either there is no such line, or it has no refund slot.
     *
     * <p>A 404 rather than an invented state. The contract's {@code state} is required and has no "unknown", so
     * there is no honest answer for a line whose slot cannot be read — and defaulting to {@code FREE} would be a
     * claim about money that nothing observed (docs/agent-spec.md:36).
     */
    public static class RefundStatusNotFoundException extends RuntimeException {

        private final transient String lineId;

        public RefundStatusNotFoundException(String lineId) {
            super("no refund status for line " + lineId);
            this.lineId = lineId;
        }

        public String lineId() {
            return lineId;
        }
    }
}
