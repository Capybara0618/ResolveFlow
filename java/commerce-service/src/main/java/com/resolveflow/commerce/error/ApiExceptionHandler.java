package com.resolveflow.commerce.error;

import com.resolveflow.commerce.internal.OrderLineController;
import com.resolveflow.commerce.order.OrderLineCursor;
import com.resolveflow.shared.error.ApiError;
import jakarta.servlet.http.HttpServletRequest;
import java.util.UUID;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.http.converter.HttpMessageNotReadableException;
import org.springframework.web.bind.MissingServletRequestParameterException;
import org.springframework.web.bind.annotation.ExceptionHandler;
import org.springframework.web.bind.annotation.RestControllerAdvice;
import org.springframework.web.method.annotation.MethodArgumentTypeMismatchException;

/**
 * This service's failures in the one shared error body {@code {code, message, retryable, trace_id,
 * details}} (docs/contracts.md:14).
 *
 * <p>Only the paths the read surface can actually hit are mapped: a missing or malformed scope is
 * 400 rather than a 500, and a cursor this service did not issue is 400 rather than a silently
 * ignored parameter — a caller that sends a broken cursor should be told, not given page one again.
 */
@RestControllerAdvice
public class ApiExceptionHandler {

    @ExceptionHandler(OrderLineController.LineNotFoundException.class)
    public ResponseEntity<ApiError> lineNotFound(
            OrderLineController.LineNotFoundException error, HttpServletRequest request) {
        return ResponseEntity.status(HttpStatus.NOT_FOUND)
                .contentType(org.springframework.http.MediaType.APPLICATION_JSON)
                .body(ApiError.of("NOT_FOUND", error.getMessage(), false, traceId(request)));
    }

    @ExceptionHandler({
        MissingServletRequestParameterException.class,
        MethodArgumentTypeMismatchException.class,
        HttpMessageNotReadableException.class,
        IllegalArgumentException.class
    })
    public ResponseEntity<ApiError> invalidArgument(Exception error, HttpServletRequest request) {
        return ResponseEntity.status(HttpStatus.BAD_REQUEST)
                .body(ApiError.of("INVALID_ARGUMENT", messageOf(error), false, traceId(request)));
    }

    private static String messageOf(Exception error) {
        if (error instanceof OrderLineCursor.InvalidCursorException) {
            return "cursor was not issued by this service";
        }
        if (error instanceof MissingServletRequestParameterException missing) {
            return "missing required parameter " + missing.getParameterName();
        }
        if (error instanceof MethodArgumentTypeMismatchException mismatch) {
            return "parameter " + mismatch.getName() + " has the wrong type";
        }
        if (error instanceof HttpMessageNotReadableException) {
            return "request body is not a valid JSON object with exactly the documented members";
        }
        return error.getMessage() == null ? "the request was refused" : error.getMessage();
    }

    private static String traceId(HttpServletRequest request) {
        String supplied = request == null ? null : request.getHeader("X-Request-Id");
        if (supplied != null && !supplied.isBlank() && supplied.length() <= 128) {
            return supplied;
        }
        return UUID.randomUUID().toString();
    }
}
