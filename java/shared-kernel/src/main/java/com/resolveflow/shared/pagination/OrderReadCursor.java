package com.resolveflow.shared.pagination;

import java.nio.charset.StandardCharsets;
import java.time.Instant;
import java.util.Base64;

/** Internal keyset protocol shared by Commerce and Case's multi-store merge; accepts legacy millisecond cursors. */
public record OrderReadCursor(Instant paidAt, String lineId) {
    public OrderReadCursor {
        if (paidAt == null || lineId == null || lineId.isBlank() || lineId.length() > 64)
            throw new IllegalArgumentException("invalid order cursor anchor");
    }

    public String encode() {
        return Base64.getUrlEncoder()
                .withoutPadding()
                .encodeToString(("v2|" + paidAt + "|" + lineId).getBytes(StandardCharsets.UTF_8));
    }

    public static OrderReadCursor decode(String encoded) {
        if (encoded == null) return null;
        try {
            if (encoded.isBlank() || encoded.length() > 256) throw new IllegalArgumentException("invalid order cursor");
            String value = new String(Base64.getUrlDecoder().decode(encoded), StandardCharsets.UTF_8);
            if (value.startsWith("v2|")) {
                int separator = value.indexOf('|', 3);
                if (separator < 0) throw new IllegalArgumentException("invalid order cursor");
                return new OrderReadCursor(
                        Instant.parse(value.substring(3, separator)), value.substring(separator + 1));
            }
            int separator = value.indexOf(':');
            if (separator <= 0) throw new IllegalArgumentException("invalid legacy order cursor");
            return new OrderReadCursor(
                    Instant.ofEpochMilli(Long.parseLong(value.substring(0, separator))),
                    value.substring(separator + 1));
        } catch (RuntimeException error) {
            throw new IllegalArgumentException("invalid order cursor", error);
        }
    }
}
