package com.resolveflow.commerce.refund;

import com.resolveflow.shared.error.ApiError;

/**
 * A refund command this service refuses to accept.
 *
 * <p>It carries {@link RefundError} rather than only a sentence so a caller (and this service's own tests)
 * can distinguish "your message is wrong" from "the money cannot move", and so the HTTP layer can map it
 * without reading the message.
 *
 * <p>Since C05.3b it also carries the command it refused, when there was one to understand. That is what lets
 * the consumer answer the case with {@code RefundFailed} instead of dropping the command: the answer needs the
 * operation id the case fixed, and re-parsing the message to recover it would be a second, weaker reading of a
 * document this service has already read once. A refusal raised before the command could be parsed leaves it
 * {@code null} (see {@link #withCommand}): there is no operation to answer about.
 */
public class RefundRejectedException extends RuntimeException {

    private final RefundError error;

    /** The command this refusal was about, or {@code null} when the message never became one. */
    private final RefundCommand command;

    public RefundRejectedException(RefundError error, String message) {
        this(error, message, null, null);
    }

    private RefundRejectedException(RefundError error, String message, RefundCommand command, Throwable cause) {
        super(message, cause);
        this.error = error;
        this.command = command;
    }

    /**
     * The same refusal, now naming the command it was about.
     *
     * <p>Called once where the command is in scope rather than at each throw site, so a refusal added later
     * cannot forget to carry it. Returns {@code this} when a command is already attached, and keeps the
     * original refusal as the cause so the throw site it came from is not lost.
     */
    public RefundRejectedException withCommand(RefundCommand refused) {
        return command != null ? this : new RefundRejectedException(error, getMessage(), refused, this);
    }

    public RefundError error() {
        return error;
    }

    /** The command this refusal was about, or {@code null} if it never parsed into one. */
    public RefundCommand command() {
        return command;
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
