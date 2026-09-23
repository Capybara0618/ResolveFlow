package com.resolveflow.commerce.messaging;

/**
 * A publish that did not happen.
 *
 * <p>Deliberately unchecked and deliberately broad: the outbox's job is to keep the row and try again, so any
 * failure — a broker that is down, a rejected message, a timeout — has to arrive as the same signal and must
 * not be mistaken for "the call returned, therefore it is delivered" (C05.1b).
 */
public class PublishException extends RuntimeException {

    private static final long serialVersionUID = 1L;

    public PublishException(String message) {
        super(message);
    }

    public PublishException(String message, Throwable cause) {
        super(message, cause);
    }
}
