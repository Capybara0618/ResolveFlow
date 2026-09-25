-- C06.2a: the synthetic shipment adapter, read-only (docs/core-scope.md:30).
--
-- Logistics are simulated here rather than integrated. Core has no carrier API, no tracking webhooks and no
-- fulfilment writes: the Agent reads a versioned story to cite, and the contract makes the simulation visible
-- on the wire (contracts/core/openapi-commerce.yaml:500 requires `synthetic: true`). This schema is therefore
-- the *source* of a simulation, and nothing in core writes to it after this seed.
--
-- Why two tables rather than one snapshot column: the contract's snapshot carries `events` with their own
-- `source_version` each, and `source_version` as the snapshot's newest event version
-- (contracts/core/openapi-commerce.yaml:476-521). A single JSON column would make "the newest event version"
-- a fact about the parsing code; a child table makes it a fact about the rows.
--
-- `updated_at` is deliberately NOT a column. The contract requires it, and the only honest value is the
-- newest event's `occurred_at`: storing a fourth timestamp would let the snapshot's time disagree with its own
-- events, and nothing would notice. The read derives it.
--
-- Migrations are append-only (docs/engineering.md:64): this file is never edited once applied.

CREATE TABLE shipment (
    line_id            VARCHAR(64) NOT NULL,
    status             VARCHAR(64) NOT NULL,
    -- The contract's four carrier conclusions. LOST and DELIVERED are terminal; the other two are not
    -- (contracts/core/openapi-commerce.yaml CarrierConclusion).
    carrier_conclusion VARCHAR(16) NOT NULL,
    -- The newest event's version, written once by the seed and read as the snapshot's source_version. It is a
    -- version, not a count: a late event arriving with a lower version must be recognisable rather than
    -- silently overwriting newer state, and that comparison only works if the numbers came from a sequence
    -- that can skip.
    source_version     BIGINT      NOT NULL,
    PRIMARY KEY (line_id),
    CONSTRAINT fk_shipment_line FOREIGN KEY (line_id) REFERENCES order_line (line_id),
    CONSTRAINT chk_shipment_conclusion CHECK (carrier_conclusion IN ('LOST', 'DELIVERED', 'IN_TRANSIT', 'UNKNOWN')),
    CONSTRAINT chk_shipment_version CHECK (source_version >= 1)
) ENGINE = InnoDB
  DEFAULT CHARSET = utf8mb4;

-- One row per thing that happened, each with the version it happened at. Append-only by intent: a correction
-- is a new event at a higher version, never an edit of what the carrier already said.
CREATE TABLE shipment_event (
    line_id        VARCHAR(64) NOT NULL,
    code           VARCHAR(64) NOT NULL,
    occurred_at    DATETIME(6) NOT NULL,
    source_version BIGINT      NOT NULL,
    PRIMARY KEY (line_id, source_version),
    CONSTRAINT fk_event_line FOREIGN KEY (line_id) REFERENCES shipment (line_id),
    CONSTRAINT chk_event_version CHECK (source_version >= 1)
) ENGINE = InnoDB
  DEFAULT CHARSET = utf8mb4;

-- The demonstration shipments, one per seeded line. Times are absolute UTC like the order seed
-- (V2__demo_order_seed.sql), so the evidence is reproducible and a test can assert an exact instant.
--
-- 7001 is the line the core OpenAPI examples use and the one the demo case is about ("包裹丢了，希望退款"), so
-- its story ends in a lost-parcel conclusion: the evidence and the customer's words agree, which is what makes
-- the example worth having. 7101 is delivered, so a run can meet the opposite conclusion and must not treat
-- either as the answer it was hoping for. 7002 is still moving and 7201 belongs to the second merchant and
-- concludes UNKNOWN — the honest value when the carrier has not said.
INSERT INTO shipment (line_id, status, carrier_conclusion, source_version)
VALUES ('7001', 'LOST', 'LOST', 4),
       ('7002', 'IN_TRANSIT', 'IN_TRANSIT', 2),
       ('7101', 'DELIVERED', 'DELIVERED', 3),
       ('7201', 'UNKNOWN', 'UNKNOWN', 2);

-- The versions skip on purpose (7001 goes 1, 2, 4 — not 1, 2, 3). A reader that computed the snapshot's
-- version by counting events would answer 3 for a shipment whose newest event is version 4, and the test that
-- notices is the one asserting `source_version` is the maximum rather than a count.
INSERT INTO shipment_event (line_id, code, occurred_at, source_version)
VALUES ('7001', 'SHIPMENT_CREATED', '2026-09-10 12:00:00.000000', 1),
       ('7001', 'IN_TRANSIT', '2026-09-11 09:00:00.000000', 2),
       -- A version the carrier skipped: the scan that reported this event was delayed and the next one is
       -- already recorded, so the numbering is not contiguous. This is the real reason a version is not a
       -- count.
       ('7001', 'EXCEPTION_DELAYED', '2026-09-12 07:30:00.000000', 4),
       ('7002', 'SHIPMENT_CREATED', '2026-09-10 12:00:00.000000', 1),
       ('7002', 'IN_TRANSIT', '2026-09-11 09:00:00.000000', 2),
       ('7101', 'SHIPMENT_CREATED', '2026-09-11 14:00:00.000000', 1),
       ('7101', 'IN_TRANSIT', '2026-09-12 08:00:00.000000', 2),
       ('7101', 'DELIVERED', '2026-09-13 16:20:00.000000', 3),
       ('7201', 'SHIPMENT_CREATED', '2026-09-12 15:00:00.000000', 1),
       ('7201', 'HANDOVER_UNCERTAIN', '2026-09-13 10:00:00.000000', 2);