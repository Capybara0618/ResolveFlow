package com.resolveflow.caseservice.internal;

import com.fasterxml.jackson.annotation.JsonProperty;
import tools.jackson.databind.JsonNode;

/**
 * The contract's {@code AgentCallbackRequest}: one delivery from a run.
 *
 * <p>The payload is a {@link JsonNode} here because the contract types it as a {@code oneOf} without a
 * discriminator: the kind decides which shape it must be, so the shape is checked by the code that reads
 * the kind rather than by the deserializer guessing.
 *
 * <p>{@code traceparent} is nullable and is not part of what identifies the delivery (see
 * {@code AgentCallback#payloadHash}).
 */
public record AgentCallbackRequest(
        @JsonProperty("callback_id") String callbackId,
        @JsonProperty("run_id") String runId,
        @JsonProperty("input_revision") Integer inputRevision,
        String kind,
        JsonNode payload,
        String traceparent) {}
