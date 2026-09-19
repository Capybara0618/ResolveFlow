package com.resolveflow.caseservice.casefile;

/**
 * The case is not in a state that allows the requested change (409, {@code STATE_CONFLICT}).
 *
 * <p>It lives on its own rather than inside whichever service first needed it, because two of them do:
 * appending material to a case whose input is already consumed, and cancelling a case that has already
 * reached a terminal state. Both mean the same thing to a client — the transition is not available — and
 * a client should not have to learn two spellings of it.
 */
public class CaseStateConflictException extends RuntimeException {

    private static final long serialVersionUID = 1L;

    public CaseStateConflictException(String message) {
        super(message);
    }
}
