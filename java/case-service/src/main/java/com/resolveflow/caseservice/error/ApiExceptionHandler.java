package com.resolveflow.caseservice.error;

import com.resolveflow.caseservice.auth.LoginRequest.InvalidLoginRequestException;
import com.resolveflow.shared.error.ApiError;
import com.resolveflow.shared.security.DemoAccounts;
import com.resolveflow.shared.security.JwtCodec;
import jakarta.servlet.http.HttpServletRequest;
import java.util.UUID;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.http.converter.HttpMessageNotReadableException;
import org.springframework.web.bind.annotation.ExceptionHandler;
import org.springframework.web.bind.annotation.RestControllerAdvice;

/**
 * Turns the failures of this service into the one shared error body
 * {@code {code, message, retryable, trace_id, details}} (docs/contracts.md:14).
 *
 * <p>Two rules are load-bearing: a rejected login is 401 with one message for both a wrong password
 * and an unknown account (so the endpoint cannot be used to enumerate users), and a malformed body —
 * including an unknown member, since the core schemas are {@code additionalProperties: false} — is
 * 400 rather than a 500 with a stack trace.
 *
 * <p>{@code trace_id} is taken from the caller's {@code X-Request-Id} when present and generated
 * otherwise, so an error is always correlatable instead of carrying a placeholder.
 */
@RestControllerAdvice
public class ApiExceptionHandler {

    private static final Logger LOG = LoggerFactory.getLogger(ApiExceptionHandler.class);

    @ExceptionHandler(DemoAccounts.CredentialsRejectedException.class)
    public ResponseEntity<ApiError> unauthenticated(
            DemoAccounts.CredentialsRejectedException error, HttpServletRequest request) {
        LOG.debug("login refused: {}", error.getMessage());
        return ResponseEntity.status(HttpStatus.UNAUTHORIZED)
                .body(ApiError.of("UNAUTHENTICATED", error.getMessage(), false, traceId(request)));
    }

    @ExceptionHandler({InvalidLoginRequestException.class, HttpMessageNotReadableException.class})
    public ResponseEntity<ApiError> invalidArgument(Exception error, HttpServletRequest request) {
        String message = error instanceof InvalidLoginRequestException
                ? error.getMessage()
                : "request body is not a valid JSON object with exactly the documented members";
        return ResponseEntity.status(HttpStatus.BAD_REQUEST)
                .body(ApiError.of("INVALID_ARGUMENT", message, false, traceId(request)));
    }

    /** A rejected user token is an authentication failure, never a 500. */
    @ExceptionHandler(JwtCodec.TokenException.class)
    public ResponseEntity<ApiError> tokenRefused(JwtCodec.TokenException error, HttpServletRequest request) {
        LOG.debug("token refused: {}", error.getMessage());
        return ResponseEntity.status(HttpStatus.UNAUTHORIZED)
                .body(ApiError.of("UNAUTHENTICATED", "the bearer token was refused", false, traceId(request)));
    }

    private static String traceId(HttpServletRequest request) {
        String supplied = request == null ? null : request.getHeader("X-Request-Id");
        if (supplied != null && !supplied.isBlank() && supplied.length() <= 128) {
            return supplied;
        }
        return UUID.randomUUID().toString();
    }
}
