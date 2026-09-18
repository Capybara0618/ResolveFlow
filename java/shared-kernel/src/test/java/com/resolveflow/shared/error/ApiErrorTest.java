package com.resolveflow.shared.error;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

import java.util.Map;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import tools.jackson.databind.ObjectMapper;

/**
 * The error body is a cross-language contract (docs/contracts.md:14), so the wire
 * field names matter more than the Java names. These tests pin the JSON shape.
 */
class ApiErrorTest {

    private final ObjectMapper mapper = new ObjectMapper();

    @Test
    @DisplayName("Serialises to the documented field names, including snake_case trace_id")
    void serialisesToContractFieldNames() {
        String json = mapper.writeValueAsString(
                new ApiError("ENTITLEMENT_CONFLICT", "line already held", false, "trace-1", null));

        assertThat(json).contains("\"code\":\"ENTITLEMENT_CONFLICT\"");
        assertThat(json).contains("\"message\":\"line already held\"");
        assertThat(json).contains("\"retryable\":false");
        assertThat(json).contains("\"trace_id\":\"trace-1\"");
        // Absent rather than null, so consumers can rely on presence.
        assertThat(json).doesNotContain("details");
        // Guard against someone renaming the record component without updating the contract.
        assertThat(json).doesNotContain("traceId");
    }

    @Test
    @DisplayName("retryable is carried explicitly, not inferred from the status code")
    void carriesRetryabilityExplicitly() {
        // 503 upstream unavailable: retryable.
        String retryable =
                mapper.writeValueAsString(ApiError.of("UPSTREAM_UNAVAILABLE", "provider timeout", true, "t-1"));
        assertThat(retryable).contains("\"retryable\":true");

        // 409 conflict: not retryable, even though a naive caller might retry it.
        String conflict =
                mapper.writeValueAsString(ApiError.of("ENTITLEMENT_CONFLICT", "line already held", false, "t-2"));
        assertThat(conflict).contains("\"retryable\":false");
    }

    @Test
    @DisplayName("details are carried when present and made immutable")
    void carriesDetails() {
        String json = mapper.writeValueAsString(
                new ApiError("VALIDATION_FAILED", "bad input", false, "t-3", Map.of("field", "amount_minor")));
        assertThat(json).contains("\"details\":{\"field\":\"amount_minor\"}");
    }

    @Test
    @DisplayName("A blank code is refused rather than silently serialised")
    void rejectsBlankCode() {
        assertThatThrownBy(() -> ApiError.of("  ", "msg", false, "t")).isInstanceOf(IllegalArgumentException.class);
    }

    @Test
    @DisplayName("Round-trips through Jackson 3")
    void roundTrips() {
        ApiError original = ApiError.of("NOT_FOUND", "no such line", false, "t-4");
        ApiError parsed = mapper.readValue(mapper.writeValueAsString(original), ApiError.class);
        assertThat(parsed).isEqualTo(original);
    }
}
