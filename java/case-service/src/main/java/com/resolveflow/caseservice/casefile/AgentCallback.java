package com.resolveflow.caseservice.casefile;

import com.fasterxml.jackson.annotation.JsonProperty;
import com.resolveflow.shared.contract.CanonicalJson;
import java.time.Instant;
import java.util.List;
import tools.jackson.databind.JsonNode;
import tools.jackson.databind.ObjectMapper;
import tools.jackson.databind.node.ObjectNode;

/**
 * One delivery from a run, validated against the contract's {@code AgentCallbackRequest}.
 *
 * <p>The envelope and the payload are one record because neither is meaningful alone: the kind decides which
 * payload is required, and the revision decides whether the delivery still applies to the case. Parsing them
 * separately would let a caller combine a kind with the wrong payload object and have both halves look valid.
 *
 * <p>{@code payload} stays a {@link JsonNode} in the request and is converted per kind, because the contract
 * types the payload with {@code oneOf} plus {@code if}/{@code then} rather than a discriminator member: there is
 * no field to switch on, so the switch is the {@code kind}. A payload that does not match its kind fails here
 * rather than being stored as an opaque blob nobody validated.
 */
public record AgentCallback(
        String callbackId, String runId, int inputRevision, Kind kind, JsonNode payload, String traceparent) {

    /** The contract's {@code CallbackKind}. */
    public enum Kind {
        STARTED,
        QUESTION,
        PROPOSAL,
        FAILED;

        public static Kind of(String value) {
            try {
                return valueOf(value);
            } catch (IllegalArgumentException | NullPointerException error) {
                throw new CaseService.SemanticInvalidException(
                        "kind must be one of STARTED, QUESTION, PROPOSAL, FAILED");
            }
        }
    }

    /** The contract's {@code CallbackDisposition}. */
    public enum Disposition {
        ACCEPTED,
        DUPLICATE,
        STALE
    }

    public static final int MAX_CALLBACK_ID = 64;

    public static final int MAX_QUESTIONS = 3;

    /**
     * What was delivered, hashed for the redelivery decision.
     *
     * <p>{@code traceparent} is deliberately not part of it: a redelivery is often a new trace of the same
     * delivery, and treating that as a different payload would answer a broken producer's retry with a
     * conflict. {@code callback_id} is included because the hash is compared together with the id it belongs
     * to, and a hash that does not cover the id could not tell two ids apart if a caller reused one.
     */
    public String payloadHash(ObjectMapper mapper) {
        ObjectNode node = mapper.createObjectNode();
        node.put("callback_id", callbackId);
        node.put("run_id", runId);
        node.put("input_revision", inputRevision);
        node.put("kind", kind.name());
        node.set("payload", payload);
        return CanonicalJson.contentHash(node);
    }

    /**
     * The payload read as the record its kind requires.
     *
     * <p>The caller's {@code ObjectMapper} is used rather than a fresh one, so the strict "no unknown
     * members" setting that the core schemas need applies here too: a payload with an extra member is a
     * protocol error, not something to drop silently.
     */
    public <T> T payload(ObjectMapper mapper, Class<T> type) {
        try {
            return mapper.treeToValue(payload, type);
        } catch (RuntimeException error) {
            throw new CaseService.SemanticInvalidException(
                    "payload does not match kind " + kind + ": " + firstLine(error.getMessage()));
        }
    }

    private static String firstLine(String message) {
        if (message == null) {
            return "unreadable";
        }
        int newline = message.indexOf('\n');
        return newline < 0 ? message : message.substring(0, newline);
    }

    /**
     * {@code StartedPayload}: the run began.
     *
     * <p>The members are annotated rather than spelled the same, because the wire is snake_case and there
     * is no global naming strategy in this service: a record that relied on the name matching would bind
     * nothing, and strict unknown-member handling would turn that into a refusal of a valid delivery.
     */
    public record Started(@JsonProperty("started_at") Instant startedAt) {}

    /** One aggregated question ({@code AgentQuestion}): a field to fill and the prompt asking for it. */
    public record QuestionItem(String field, String prompt) {}

    /** {@code QuestionPayload}: at most three questions under one stable id. */
    public record Questions(
            @JsonProperty("question_id") String questionId,
            List<QuestionItem> questions,
            @JsonProperty("reason_codes") List<String> reasonCodes) {}

    /** {@code FailedPayload}: why the run stopped, and whether trying again could help. */
    public record Failure(
            @JsonProperty("reason_codes") List<String> reasonCodes,
            boolean retryable,
            @JsonProperty("last_observation_refs") List<String> lastObservationRefs) {}
}
