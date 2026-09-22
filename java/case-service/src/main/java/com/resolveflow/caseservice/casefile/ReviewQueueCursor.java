package com.resolveflow.caseservice.casefile;

import java.time.Instant;
import java.util.Base64;
import java.util.List;

/**
 * The opaque keyset cursor of the review queue (C03.2c).
 *
 * <p>Keyset rather than offset, for the reason the order listing already settled: an offset skips or
 * repeats rows when a case moves between two pages, and a case moving is exactly what this queue is
 * about — every row in it got there by being updated.
 *
 * <p>It is the last row's {@code (updated_at, case_id)}, the same pair the query is ordered by. The
 * {@code case_id} is the tie-breaker, not decoration: two cases can share {@code updated_at} down to the
 * microsecond when one request opens several, and without it the page boundary would be a coin toss.
 *
 * <p>Opaque to the caller but not secret, and it carries no scope: the merchant always comes from the
 * verified principal, so a cursor cannot be turned into a way to read another merchant's queue.
 */
public record ReviewQueueCursor(Instant updatedAt, String caseId) {

    private static final Base64.Encoder ENCODER = Base64.getUrlEncoder().withoutPadding();
    private static final Base64.Decoder DECODER = Base64.getUrlDecoder();

    /**
     * Raised for a cursor this service did not issue.
     *
     * <p>It exists as its own type so the API layer can answer 400 rather than letting a client mistake
     * become a 500 — or, worse, be treated as "no cursor" and silently restart the listing, which would
     * make a paging bug look like a short queue.
     */
    public static class InvalidCursorException extends RuntimeException {

        private static final long serialVersionUID = 1L;

        public InvalidCursorException(String message) {
            super(message);
        }

        public InvalidCursorException(String message, Throwable cause) {
            super(message, cause);
        }
    }

    public String encode() {
        return ENCODER.encodeToString(
                (updatedAt.toEpochMilli() + ":" + caseId).getBytes(java.nio.charset.StandardCharsets.UTF_8));
    }

    public static ReviewQueueCursor decode(String encoded) {
        if (encoded == null || encoded.isBlank()) {
            return null;
        }
        String decoded;
        try {
            decoded = new String(DECODER.decode(encoded), java.nio.charset.StandardCharsets.UTF_8);
        } catch (IllegalArgumentException error) {
            throw new InvalidCursorException("cursor is not valid base64url", error);
        }
        int separator = decoded.indexOf(':');
        if (separator <= 0 || separator == decoded.length() - 1) {
            throw new InvalidCursorException("cursor is not an updated_at:case_id pair");
        }
        Instant updatedAt;
        try {
            updatedAt = Instant.ofEpochMilli(Long.parseLong(decoded.substring(0, separator)));
        } catch (NumberFormatException error) {
            throw new InvalidCursorException("cursor does not carry an updated_at", error);
        }
        return new ReviewQueueCursor(updatedAt, decoded.substring(separator + 1));
    }

    /**
     * The cursor that continues after the last row of a page, or null when the queue ends here.
     *
     * <p>Null is how the response says "no more": a cursor that yields an empty page would make every
     * client ask one question too many.
     */
    public static String after(List<ReviewQueueRow> pageOfLimit, boolean hasMore) {
        if (!hasMore || pageOfLimit.isEmpty()) {
            return null;
        }
        ReviewQueueRow last = pageOfLimit.get(pageOfLimit.size() - 1);
        return new ReviewQueueCursor(last.updatedAt(), last.caseId()).encode();
    }
}
