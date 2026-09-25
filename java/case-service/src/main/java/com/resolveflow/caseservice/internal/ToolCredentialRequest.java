package com.resolveflow.caseservice.internal;

import com.fasterxml.jackson.annotation.JsonProperty;

/**
 * {@code ToolCredentialRequest}: the revision a credential is being renewed for (C06.4④).
 *
 * <p>{@code contracts/core/openapi-case.yaml:2318} declares exactly these two members and nothing else
 * ({@code additionalProperties: false}), so a body that names a run, a line or a merchant is not a request this
 * route can honour — those are facts the run binding and the case row already own, and accepting them from a
 * caller would be accepting the caller's word for who it is.
 *
 * <p>{@code input_revision} is an {@code int} here rather than a {@code long} or a boxed type: the contract's
 * {@code InputRevision} is a positive integer and a missing member must be a refusal, not silently zero.
 */
public record ToolCredentialRequest(
        @JsonProperty("case_id") String caseId,
        @JsonProperty("input_revision") int inputRevision) {}
