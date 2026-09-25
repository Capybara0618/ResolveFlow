package com.resolveflow.caseservice.internal;

import com.fasterxml.jackson.annotation.JsonProperty;
import java.time.Instant;
import java.util.List;

/**
 * {@code ToolCredentialResponse}: the scoped credential and the two facts a caller needs about it (C06.4④).
 *
 * <p>The mirror of {@code contracts/core/openapi-case.yaml:2330}. All three members are required by the
 * contract, so none is nullable and none is optional: a credential whose expiry a caller had to guess would be
 * renewed either too late (a tool that fails halfway) or too often (a mint per call).
 *
 * <p>{@code scopes} is a list on the wire and a single space-delimited string inside the token, because the JWT
 * {@code scope} claim is one string (RFC 6749's spelling). Both are asserted in
 * {@code ToolCredentialApiTest}, so the two representations cannot drift apart unnoticed.
 */
public record ToolCredentialResponse(
        @JsonProperty("token") String token,
        @JsonProperty("expires_at") Instant expiresAt,
        @JsonProperty("scopes") List<String> scopes) {}
