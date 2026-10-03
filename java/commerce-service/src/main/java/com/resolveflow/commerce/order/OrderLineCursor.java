package com.resolveflow.commerce.order;

import java.time.Instant;
import java.util.Base64;
import java.util.List;

/**
 * The opaque keyset cursor of the order-line listing.
 *
 * <p>Keyset rather than offset: the core baseline already ruled out deep offsets
 * (docs/contracts.md:15, "Cursor paging on created_at+id"), and an offset would also skip or repeat
 * rows when a new order arrives between two pages. The cursor is the last row's
 * {@code (paid_at, line_id)} — the same pair the index is ordered by.
 *
 * <p>It is opaque to the caller but not secret, and it carries no scope: the scope always comes from
 * the caller's verified principal, so a cursor cannot be turned into a way to read another tenant's
 * lines (docs/core-contracts.md:15).
 */
public record OrderLineCursor(Instant paidAt, String lineId) {

    private static final Base64.Encoder ENCODER = Base64.getUrlEncoder().withoutPadding();
    private static final Base64.Decoder DECODER = Base64.getUrlDecoder();

    /** Raised for a cursor this service did not issue; the API layer turns it into a 400. */
    public static class InvalidCursorException extends IllegalArgumentException {

        private static final long serialVersionUID = 1L;

        public InvalidCursorException(String message, Throwable cause) {
            super(message, cause);
        }

        public InvalidCursorException(String message) {
            super(message);
        }
    }

    public String encode() {
        return new com.resolveflow.shared.pagination.OrderReadCursor(paidAt, lineId).encode();
    }

    public static OrderLineCursor decode(String encoded) {
        if (encoded == null) {
            return null;
        }
        try {
            var cursor = com.resolveflow.shared.pagination.OrderReadCursor.decode(encoded);
            return new OrderLineCursor(cursor.paidAt(), cursor.lineId());
        } catch (RuntimeException error) {
            throw new InvalidCursorException("cursor was not issued by this service", error);
        }
    }

    /**
     * Build the cursor that continues after the last row of a page.
     *
     * <p>Returns null when there is no next page, which is how the response says "the end" — with a
     * null {@code next_cursor} rather than a cursor that yields nothing.
     */
    public static String after(List<OrderLineRow> pageOfLimit, boolean hasMore) {
        if (!hasMore) {
            return null;
        }
        OrderLineRow last = pageOfLimit.get(pageOfLimit.size() - 1);
        return new OrderLineCursor(last.paidAt(), last.lineId()).encode();
    }
}
