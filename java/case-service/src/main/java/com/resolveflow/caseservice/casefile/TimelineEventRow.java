package com.resolveflow.caseservice.casefile;

import java.time.Instant;

/**
 * One trajectory row as {@code case_timeline} holds it.
 *
 * <p>{@code eventId} is stored rather than derived from the sequence number: a derived id would change
 * meaning as soon as the case gained input revisions, and an event id that moves is not an identity.
 *
 * <p>{@code kind} is a member of the contract's {@code TimelineEventType} — the migration's CHECK
 * constraint says so — and {@code inputRevision} is the revision the event belongs to, not the case's
 * current revision.
 */
public record TimelineEventRow(
        String caseId,
        String eventId,
        int sequence,
        TimelineEventType kind,
        String detail,
        Instant occurredAt,
        int inputRevision) {}
