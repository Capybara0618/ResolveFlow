package com.resolveflow.caseservice.casefile;

import com.fasterxml.jackson.annotation.JsonProperty;

/**
 * What the decision route answers, member for member with the contract's {@code ReviewResponse}.
 *
 * <p>Both versions are reported because both moved: the authorisation's own version (the decision bumped it,
 * so a second decision with the same body is stale) and the case's (an approval moved the case on, a
 * rejection ended it). A caller that only got the status would have to re-read the case to find out what it
 * is now looking at.
 */
public record ReviewResponse(
        @JsonProperty("case_id") String caseId,
        @JsonProperty("authorization_id") String authorizationId,
        @JsonProperty("authorization_version") long authorizationVersion,
        AuthorizationStatus status,
        @JsonProperty("case_version") long caseVersion) {}
