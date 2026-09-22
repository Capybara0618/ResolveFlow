package com.resolveflow.caseservice.casefile;

import com.fasterxml.jackson.annotation.JsonProperty;

/**
 * The decision a reviewer submits, member for member with the contract's {@code ReviewRequest}.
 *
 * <p>{@code authorizationVersion} is the version the reviewer saw, which is why it is in the body while the
 * case version travels in {@code If-Match}: one guards the decision (nobody may decide a version that has
 * already moved), the other guards the reading it was made from.
 *
 * <p>{@code authorizationId} and {@code decision} stay strings here and are parsed by the service, so that a
 * malformed request is this service's own 422 with a sentence naming the member rather than a deserialisation
 * failure the caller cannot act on.
 */
public record ReviewRequest(
        @JsonProperty("authorization_id") String authorizationId,
        @JsonProperty("authorization_version") Long authorizationVersion,
        String decision,
        String reason) {}
