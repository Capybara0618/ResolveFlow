package com.resolveflow.commerce.shipment;

import java.time.Instant;
import java.util.List;
import java.util.Optional;
import org.springframework.stereotype.Service;

/**
 * The synthetic shipment adapter (C06.2a).
 *
 * <p>Core ships a logistics **simulator** and says so on the wire (docs/core-scope.md:30). This service adds
 * the two things a simulation still owes a reader: the marker is a fact rather than a convention, and the
 * snapshot's version and time are derived from its own events instead of being stored beside them where the
 * three could disagree.
 *
 * <p>Nothing here decides whether the caller may see the line. The route is service-token only, and scope is
 * the caller's — Case verifies the ownership it read from the line context against the case before it cites
 * anything. A second scope check here would be a second opinion, and the one that drifted would be a way to
 * read across merchants.
 */
@Service
public class ShipmentReadService {

    /** The contract caps {@code events} at 200 items (contracts/core/openapi-commerce.yaml:514). */
    public static final int MAX_EVENTS = 200;

    private final ShipmentRepository repository;

    public ShipmentReadService(ShipmentRepository repository) {
        this.repository = repository;
    }

    /**
     * One line's shipment evidence, or empty when the line has no shipment at all.
     *
     * <p>Empty is not an empty snapshot: "this line has no shipment" and "the carrier has said nothing yet"
     * are different facts, and the second one is {@code UNKNOWN} with events. Answering the first with a
     * blank snapshot would invent a conclusion the carrier never made, which is exactly what a citation check
     * exists to prevent (docs/agent-spec.md:36 — NOT_FOUND 不是否定事实).
     */
    public Optional<ShipmentSnapshot> readShipment(String lineId) {
        if (lineId == null || lineId.isBlank()) {
            throw new IllegalArgumentException("a shipment read needs a line id");
        }
        ShipmentRepository.ShipmentRow row = repository.findShipment(lineId);
        if (row == null) {
            return Optional.empty();
        }
        List<ShipmentRepository.ShipmentEventRow> events = repository.findEvents(lineId, MAX_EVENTS);
        return Optional.of(new ShipmentSnapshot(
                row.lineId(), row.status(), row.carrierConclusion(), events, row.sourceVersion(), updatedAt(events)));
    }

    /**
     * When the snapshot was last updated: the newest event's time.
     *
     * <p>Derived rather than stored, so the snapshot cannot claim a time its own events contradict. The events
     * arrive oldest-first, so the last one is the newest — and the maximum is taken anyway, because "oldest
     * first" is the query's promise and a reader should not have to trust it twice.
     *
     * <p>A shipment with no events is a contradiction the schema cannot express (the seed always writes at
     * least one, and the contract requires a non-empty {@code updated_at}); rather than return null and let it
     * become a wire violation, the caller gets the epoch, and the test that would notice is the one asserting
     * {@code updated_at} parses. Stating it here is better than a silent null.
     */
    private static Instant updatedAt(List<ShipmentRepository.ShipmentEventRow> events) {
        Instant newest = Instant.EPOCH;
        for (ShipmentRepository.ShipmentEventRow event : events) {
            if (event.occurredAt().isAfter(newest)) {
                newest = event.occurredAt();
            }
        }
        return newest;
    }

    /**
     * The contract's {@code ShipmentSnapshot}.
     *
     * <p>{@code synthetic} is not a field: it is always true, because core has no other kind of shipment, and a
     * boolean that could be false would be a value some later step could set. The controller writes the
     * constant; this record cannot express a real carrier.
     */
    public record ShipmentSnapshot(
            String lineId,
            String status,
            String carrierConclusion,
            List<ShipmentRepository.ShipmentEventRow> events,
            long sourceVersion,
            Instant updatedAt) {

        public ShipmentSnapshot {
            events = List.copyOf(events);
        }
    }
}
