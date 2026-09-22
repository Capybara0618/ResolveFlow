package com.resolveflow.commerce.refund;

/**
 * Why a refund command was refused, as a code a caller can act on.
 *
 * <p>The split between a fault in the message and a state of the world is deliberate and matches the one
 * Case draws on its own routes: {@link #MALFORMED_COMMAND} and {@link #PAYLOAD_HASH_MISMATCH} mean the
 * message is wrong (retrying it unchanged can never work), while the rest mean the command is well-formed
 * but the money cannot move right now. A consumer that retries a malformed command forever is a consumer
 * that never reports the bug.
 */
public enum RefundError {
    MALFORMED_COMMAND("the command does not have the shape this protocol defines"),
    PAYLOAD_HASH_MISMATCH("the command's payload_hash does not cover its own members"),
    LINE_NOT_FOUND("this service has no such order line"),
    LINE_OWNER_MISMATCH("the line belongs to a different merchant"),
    AMOUNT_MISMATCH("the amount is not the line's own paid amount"),
    QUANTITY_MISMATCH("a core refund is for the line's whole quantity"),
    CURRENCY_MISMATCH("the command's currency is not the line's currency"),
    ALREADY_REFUNDED("this line has already been refunded"),
    ANOTHER_OPERATION_LIVE("another operation is currently holding this line"),
    AUTHORIZATION_ALREADY_USED("this authorisation already has a refund operation");

    private final String description;

    RefundError(String description) {
        this.description = description;
    }

    public String description() {
        return description;
    }
}
