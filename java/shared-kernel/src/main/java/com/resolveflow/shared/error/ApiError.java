package com.resolveflow.shared.error;

import com.fasterxml.jackson.annotation.JsonInclude;
import com.fasterxml.jackson.annotation.JsonProperty;
import java.util.Map;

/**
 * The error body shared by every ResolveFlow service.
 *
 * <p>Shape is fixed by docs/contracts.md:14 — {@code {code, message, retryable, trace_id,
 * details}} — with the documented status mapping: 400 input error, 401 unauthenticated,
 * 403 missing scope, 404 not visible to this principal, 409 conflict/state/version,
 * 422 semantically invalid, 429 rate limited, 503 temporarily unavailable.
 *
 * <p>{@code retryable} is carried explicitly so a caller never has to infer whether a
 * failure may be retried from the status code alone. That distinction is load-bearing
 * for the money path: a timeout is not a failure, and only an explicitly non-retryable
 * result may release a reservation.
 *
 * <p>Messages must not embed secrets, tokens or raw upstream payloads.
 */
@JsonInclude(JsonInclude.Include.NON_NULL)
public record ApiError(
        String code,
        String message,
        boolean retryable,
        @JsonProperty("trace_id") String traceId,
        Map<String, Object> details) {

    public ApiError {
        if (code == null || code.isBlank()) {
            throw new IllegalArgumentException("error code must not be blank");
        }
        details = details == null ? null : Map.copyOf(details);
    }

    public static ApiError of(String code, String message, boolean retryable, String traceId) {
        return new ApiError(code, message, retryable, traceId, null);
    }
}
