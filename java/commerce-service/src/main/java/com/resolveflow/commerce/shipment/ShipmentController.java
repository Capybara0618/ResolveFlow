package com.resolveflow.commerce.shipment;

import com.fasterxml.jackson.annotation.JsonInclude;
import com.fasterxml.jackson.annotation.JsonProperty;
import java.time.Instant;
import java.util.List;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

/**
 * {@code GET /internal/v1/order-lines/{line_id}/shipment}: the versioned synthetic shipment evidence for one
 * line (C06.2, contracts/core/openapi-commerce.yaml:127).
 *
 * <p>Its own controller rather than another method on {@link
 * com.resolveflow.commerce.internal.OrderLineController}: the shipment adapter is a different surface with a
 * different owner (C06, not C01), and keeping it separate is what lets this file be deleted or replaced when
 * real logistics arrive without touching the order reads.
 *
 * <p>{@code synthetic} is written here as the literal {@code true} rather than carried through the service's
 * record. The contract makes it required and constant (openapi-commerce.yaml:500), so a field that could hold
 * {@code false} is a field some later step could set; a constant in the response cannot be wrong. That is the
 * whole point of the marker — a reviewer must be able to tell simulated evidence from a real carrier's
 * without trusting a comment.
 *
 * <p>Times are UTC instants with a trailing Z, like the line context: the driver is pinned to UTC, so no
 * reader has to guess a zone (docs/core-contracts.md:17).
 */
@RestController
@RequestMapping("/internal/v1/order-lines")
public class ShipmentController {

    private final ShipmentReadService service;

    public ShipmentController(ShipmentReadService service) {
        this.service = service;
    }

    @GetMapping("/{line_id}/shipment")
    public ResponseEntity<ShipmentSnapshotResponse> shipment(@PathVariable("line_id") String lineId) {
        return service.readShipment(lineId)
                .map(ShipmentSnapshotResponse::from)
                .map(ResponseEntity::ok)
                .orElseThrow(() -> new ShipmentNotFoundException(lineId));
    }

    /** The contract's {@code ShipmentSnapshot}, plus the constant marker the contract requires. */
    @JsonInclude(JsonInclude.Include.NON_NULL)
    public record ShipmentSnapshotResponse(
            @JsonProperty("line_id") String lineId,
            @JsonProperty("synthetic") boolean synthetic,
            String status,
            @JsonProperty("carrier_conclusion") String carrierConclusion,
            List<ShipmentEventResponse> events,
            @JsonProperty("source_version") long sourceVersion,
            @JsonProperty("updated_at") Instant updatedAt) {

        static ShipmentSnapshotResponse from(ShipmentReadService.ShipmentSnapshot snapshot) {
            return new ShipmentSnapshotResponse(
                    snapshot.lineId(),
                    // Not a parameter and not derived: core ships a simulator, so this is the only value there
                    // is (docs/core-scope.md:30).
                    true,
                    snapshot.status(),
                    snapshot.carrierConclusion(),
                    snapshot.events().stream().map(ShipmentEventResponse::from).toList(),
                    snapshot.sourceVersion(),
                    snapshot.updatedAt());
        }
    }

    /** The contract's {@code ShipmentEvent}. */
    @JsonInclude(JsonInclude.Include.NON_NULL)
    public record ShipmentEventResponse(
            String code,
            @JsonProperty("occurred_at") Instant occurredAt,
            @JsonProperty("source_version") long sourceVersion) {

        static ShipmentEventResponse from(ShipmentRepository.ShipmentEventRow row) {
            return new ShipmentEventResponse(row.code(), row.occurredAt(), row.sourceVersion());
        }
    }

    /**
     * No shipment for this line — a 404, not an empty snapshot.
     *
     * <p>Distinct from {@link com.resolveflow.commerce.internal.OrderLineController.LineNotFoundException}
     * because the two mean different things to this caller: "there is no such line" is a reason to stop, while
     * "this line has no shipment" is a fact about the line. Both answer 404, so the agent cannot mistake either
     * for a carrier conclusion (docs/agent-spec.md:36).
     */
    public static class ShipmentNotFoundException extends RuntimeException {

        private final transient String lineId;

        public ShipmentNotFoundException(String lineId) {
            super("no shipment for line " + lineId);
            this.lineId = lineId;
        }

        public String lineId() {
            return lineId;
        }
    }
}
