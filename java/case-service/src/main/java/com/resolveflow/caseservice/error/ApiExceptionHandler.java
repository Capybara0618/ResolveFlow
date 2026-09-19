package com.resolveflow.caseservice.error;

import com.resolveflow.caseservice.auth.LoginRequest.InvalidLoginRequestException;
import com.resolveflow.caseservice.casefile.CaseService;
import com.resolveflow.caseservice.order.CommerceOrderLineClient;
import com.resolveflow.caseservice.order.OrderController;
import com.resolveflow.caseservice.order.RequestPrincipalResolver;
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

    /** A protected route reached without a usable token (C01.2c). */
    @ExceptionHandler(RequestPrincipalResolver.UnauthenticatedException.class)
    public ResponseEntity<ApiError> unauthenticated(
            RequestPrincipalResolver.UnauthenticatedException error, HttpServletRequest request) {
        LOG.debug("principal could not be resolved: {}", error.getMessage());
        return ResponseEntity.status(HttpStatus.UNAUTHORIZED)
                .body(ApiError.of("UNAUTHENTICATED", error.getMessage(), false, traceId(request)));
    }

    /**
     * An order the principal cannot see is 404, never 403 (docs/core-contracts.md:27).
     *
     * <p>The message is the generic one the contract uses for this surface, so the answer to "is this
     * order someone else's?" is the same as the answer to "does this order exist?".
     */
    @ExceptionHandler(OrderController.OrderNotVisibleException.class)
    public ResponseEntity<ApiError> notVisible(
            OrderController.OrderNotVisibleException error, HttpServletRequest request) {
        return ResponseEntity.status(HttpStatus.NOT_FOUND)
                .body(ApiError.of("NOT_FOUND", error.getMessage(), false, traceId(request)));
    }

    /**
     * Commerce being unreachable is this service's problem, not the caller's: 503 and retryable, so
     * the caller does not read it as "your order does not exist" and does not treat a timeout as a
     * refusal. A timeout is never a failed refund, and it is never a missing order either.
     */
    @ExceptionHandler(CommerceOrderLineClient.CommerceUnavailableException.class)
    public ResponseEntity<ApiError> commerceUnavailable(
            CommerceOrderLineClient.CommerceUnavailableException error, HttpServletRequest request) {
        LOG.warn("commerce is unavailable: {}", error.getMessage());
        return ResponseEntity.status(HttpStatus.SERVICE_UNAVAILABLE)
                .body(ApiError.of(
                        "SERVICE_UNAVAILABLE", "the order service is temporarily unavailable", true, traceId(request)));
    }

    /** A create request that is well formed but asks for something core cannot honour. */
    @ExceptionHandler(CaseService.SemanticInvalidException.class)
    public ResponseEntity<ApiError> semanticInvalid(
            CaseService.SemanticInvalidException error, HttpServletRequest request) {
        return ResponseEntity.status(HttpStatus.UNPROCESSABLE_CONTENT)
                .body(ApiError.of("SEMANTIC_INVALID", error.getMessage(), false, traceId(request)));
    }

    /** The Idempotency-Key header is part of the route, not optional advice. */
    @ExceptionHandler(CaseService.MissingIdempotencyKeyException.class)
    public ResponseEntity<ApiError> missingIdempotencyKey(
            CaseService.MissingIdempotencyKeyException error, HttpServletRequest request) {
        return ResponseEntity.status(HttpStatus.BAD_REQUEST)
                .body(ApiError.of("INVALID_ARGUMENT", error.getMessage(), false, traceId(request)));
    }

    /**
     * Two different 409s, because they ask the caller for different things.
     *
     * <p>A repeated key with a different body is `IDEMPOTENCY_CONFLICT` and is not retryable: the
     * caller must use a new key. A line that already has an open case is `CASE_ALREADY_OPEN`:
     * retrying changes nothing, and the caller should read the case that exists
     * (docs/domain-model.md:26). Reusing one code for both would tell a client to retry a request
     * that can never succeed.
     */
    @ExceptionHandler(CaseService.IdempotencyConflictException.class)
    public ResponseEntity<ApiError> idempotencyConflict(
            CaseService.IdempotencyConflictException error, HttpServletRequest request) {
        return ResponseEntity.status(HttpStatus.CONFLICT)
                .body(ApiError.of("IDEMPOTENCY_CONFLICT", error.getMessage(), false, traceId(request)));
    }

    @ExceptionHandler(CaseService.CaseAlreadyOpenException.class)
    public ResponseEntity<ApiError> caseAlreadyOpen(
            CaseService.CaseAlreadyOpenException error, HttpServletRequest request) {
        return ResponseEntity.status(HttpStatus.CONFLICT)
                .body(ApiError.of("CASE_ALREADY_OPEN", error.getMessage(), false, traceId(request)));
    }

    /** An invisible line is 404, exactly like an invisible order (docs/core-contracts.md:27). */
    @ExceptionHandler(CaseService.LineNotVisibleException.class)
    public ResponseEntity<ApiError> lineNotVisible(
            CaseService.LineNotVisibleException error, HttpServletRequest request) {
        return ResponseEntity.status(HttpStatus.NOT_FOUND)
                .body(ApiError.of("NOT_FOUND", error.getMessage(), false, traceId(request)));
    }

    @ExceptionHandler(CaseService.ForbiddenScopeException.class)
    public ResponseEntity<ApiError> forbiddenScope(
            CaseService.ForbiddenScopeException error, HttpServletRequest request) {
        return ResponseEntity.status(HttpStatus.FORBIDDEN)
                .body(ApiError.of("FORBIDDEN_SCOPE", error.getMessage(), false, traceId(request)));
    }

    /** A Commerce answer this service cannot read is a bug here, not a caller error. */
    @ExceptionHandler(CommerceOrderLineClient.CommerceProtocolException.class)
    public ResponseEntity<ApiError> commerceProtocol(
            CommerceOrderLineClient.CommerceProtocolException error, HttpServletRequest request) {
        LOG.error("commerce answered something this service cannot read: {}", error.getMessage());
        return ResponseEntity.status(HttpStatus.SERVICE_UNAVAILABLE)
                .body(ApiError.of(
                        "SERVICE_UNAVAILABLE",
                        "the order service answered an unusable response",
                        true,
                        traceId(request)));
    }

    private static String traceId(HttpServletRequest request) {
        String supplied = request == null ? null : request.getHeader("X-Request-Id");
        if (supplied != null && !supplied.isBlank() && supplied.length() <= 128) {
            return supplied;
        }
        return UUID.randomUUID().toString();
    }
}
