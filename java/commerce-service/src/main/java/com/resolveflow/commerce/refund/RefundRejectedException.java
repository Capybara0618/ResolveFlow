package com.resolveflow.commerce.refund;

import com.resolveflow.shared.error.ApiError;

/**
 * A refund command this service refuses to accept.
 *
 * <p>It carries {@link RefundError} rather than only a sentence so a caller (and this service's own tests)
 * can distinguish "your message is wrong" from "the money cannot move", and so the HTTP layer can map it
 * without reading the message.
 */
public class RefundRejectedException extends RuntimeException {

    private final RefundError error;

    public RefundRejectedException(RefundError error, String message) {
        super(message);
        this.error = error;
    }

    public RefundError error() {
        return error;
    }

    /** 409 when the world is what refused, 400 when the message is. */
    public boolean isConflict() {
        return switch (error) {
            case MALFORMED_COMMAND, PAYLOAD_HASH_MISMATCH, LINE_NOT_FOUND -> false;
            default -> true;
        };
    }

    public ApiError toApiError(String traceId) {
        return ApiError.of(error.name(), getMessage(), false, traceId);
    }
}
