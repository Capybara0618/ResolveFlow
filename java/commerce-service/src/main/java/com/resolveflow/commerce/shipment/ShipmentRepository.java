package com.resolveflow.commerce.shipment;

import java.time.Instant;
import java.util.List;
import org.apache.ibatis.annotations.Mapper;
import org.apache.ibatis.annotations.Param;
import org.apache.ibatis.annotations.Select;

/**
 * The synthetic shipment adapter's reads (V6__commerce_shipment_adapter.sql).
 *
 * <p>Reads only. First shipment and the local V16 simulator own logistics writes; the Agent never does.
 *
 * <p>Both reads are by line id alone. That is safe here for the same reason the line-context read is
 * (C03.2a): the caller is the service that already decided the line is in scope, and this route is
 * service-token only. The endpoint has no scope of its own to enforce, and it must not invent one that could
 * disagree with the caller's.
 */
@Mapper
public interface ShipmentRepository {

    /**
     * The snapshot row, or null when this line has no shipment.
     *
     * <p>{@code updated_at} is not selected: it is the newest event's time, and it is read from the events so
     * the snapshot cannot carry a time that disagrees with them.
     */
    @Select("""
            SELECT line_id            AS lineId,
                   status             AS status,
                   carrier_conclusion AS carrierConclusion,
                   source_version     AS sourceVersion
              FROM shipment
             WHERE line_id = #{lineId}
            """)
    ShipmentRow findShipment(@Param("lineId") String lineId);

    @Select("""
            SELECT COUNT(*)>0 FROM shipment_simulation_fault f
            JOIN order_line l ON l.order_id=f.order_id
            WHERE l.line_id=#{lineId} AND f.unavailable=TRUE
            """)
    boolean queryUnavailable(@Param("lineId") String lineId);

    /**
     * The events, oldest first.
     *
     * <p>Ordered by version rather than by time: the version is the carrier's own ordering and the one a late
     * event is judged against, while two events can share an instant (a scan and its handover). Ordered
     * ascending so a reader sees the story in the order it happened, and the newest is last.
     *
     * <p>Bounded by {@code limit} because the contract caps the array at 200 items
     * (contracts/core/openapi-commerce.yaml:514). The bound is applied in the query rather than by taking the
     * first 200 of everything: a line with ten thousand events must not be read into memory to be truncated.
     */
    @Select("""
            SELECT code           AS code,
                   occurred_at    AS occurredAt,
                   source_version AS sourceVersion
              FROM shipment_event
             WHERE line_id = #{lineId}
             ORDER BY source_version
             LIMIT #{limit}
            """)
    List<ShipmentEventRow> findEvents(@Param("lineId") String lineId, @Param("limit") int limit);

    /** One shipment's current state. */
    record ShipmentRow(String lineId, String status, String carrierConclusion, long sourceVersion) {}

    /** One thing the carrier said, at the version it said it. */
    record ShipmentEventRow(String code, Instant occurredAt, long sourceVersion) {}
}
