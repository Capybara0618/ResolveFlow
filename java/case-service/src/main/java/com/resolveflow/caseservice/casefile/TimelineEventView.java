package com.resolveflow.caseservice.casefile;

import com.fasterxml.jackson.annotation.JsonInclude;
import com.fasterxml.jackson.annotation.JsonProperty;
import java.time.Instant;

/**
 * One trajectory row as a client sees it.
 *
 * <p>It exists so the case view and the event stream cannot drift: both render the same stored facts
 * through this one mapping, so a client that reads the timeline once and then streams it is looking at
 * the same shape of thing (docs/core-contracts.md:29).
 */
@JsonInclude(JsonInclude.Include.NON_NULL)
public record TimelineEventView(
        @JsonProperty("event_id") String eventId,
        TimelineEventType type,
        @JsonProperty("occurred_at") Instant occurredAt,
        String summary,
        Integer revision) {

    static TimelineEventView of(TimelineEventRow row) {
        return new TimelineEventView(
                row.eventId(), row.kind(), row.occurredAt(), TimelineSummary.of(row), row.inputRevision());
    }
}
