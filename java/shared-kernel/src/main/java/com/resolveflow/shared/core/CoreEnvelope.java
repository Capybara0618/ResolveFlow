package com.resolveflow.shared.core;

import com.resolveflow.shared.contract.CanonicalJson;
import java.nio.charset.StandardCharsets;
import java.security.PrivateKey;
import java.security.PublicKey;
import java.time.Instant;
import java.util.Base64;
import tools.jackson.databind.JsonNode;
import tools.jackson.databind.ObjectMapper;
import tools.jackson.databind.node.ObjectNode;

/**
 * Building and reading a core event envelope (contracts/core/event-envelope.schema.json).
 *
 * <p>The envelope's shape is not decoration: {@code producer} and {@code topic} are selected by the event
 * type, and both are inside the signed bytes. A producer that "helpfully" kept the topic outside the
 * signature would let a message be re-addressed to another topic without invalidating it — which is why
 * {@link CoreEventSignature} lists {@code topic} among the signable members and why this class refuses to
 * build an envelope whose event type does not belong to the producer asking for it.
 *
 * <p>Both directions are signed in core: the command Case sends and the result Commerce sends
 * (docs/core-contracts.md:19). Verification therefore lives here too, next to the exact bytes that were
 * signed, so a consumer cannot end up checking a different normalisation than the producer used.
 */
public final class CoreEnvelope {

    /** The two topics core uses, and the only two a core envelope may carry. */
    public static final String CASE_TOPIC = "rf.case.core.v2";

    public static final String COMMERCE_TOPIC = "rf.commerce.core.v2";

    public static final String CASE_SERVICE = "case-service";

    public static final String COMMERCE_SERVICE = "commerce-service";

    public static final String REFUND_REQUESTED = "RefundRequested";

    public static final String REFUND_SUCCEEDED = "RefundSucceeded";

    public static final String REFUND_FAILED = "RefundFailed";

    public static final String REFUND_UNKNOWN = "RefundUnknown";

    /** The result states a core refund can report, one per result event type. */
    public static final String SUCCEEDED = "SUCCEEDED";

    public static final String FAILED = "FAILED";

    public static final String UNKNOWN = "UNKNOWN";

    private static final ObjectMapper MAPPER = new ObjectMapper();

    private CoreEnvelope() {}

    /** Raised when an envelope cannot be built or does not match the protocol. */
    public static class EnvelopeException extends IllegalArgumentException {

        private static final long serialVersionUID = 1L;

        public EnvelopeException(String message) {
            super(message);
        }
    }

    /**
     * Build and sign one envelope.
     *
     * @param eventId the event's own identity, allocated by the caller so the outbox row can be written in
     *     the same transaction as the effect that produced it
     * @param eventType one of the four core event types
     * @param merchantId the merchant the event is scoped to
     * @param occurredAt when the producing service decided this happened
     * @param payload the event's own body: a refund command for {@code RefundRequested}, a result otherwise
     * @param causationId what caused this event, when it is a reaction to another one
     * @param traceparent W3C trace context, carried through so a result can be joined to its command
     * @param signingKeyId which key signed it; the consumer checks it against its trust list
     */
    public static ObjectNode sign(
            String eventId,
            String eventType,
            String merchantId,
            Instant occurredAt,
            ObjectNode payload,
            String causationId,
            String traceparent,
            String signingKeyId,
            PrivateKey privateKey) {
        ObjectNode envelope =
                unsigned(eventId, eventType, merchantId, occurredAt, payload, causationId, traceparent, signingKeyId);
        envelope.put("signature", CoreEventSignature.sign(envelope, privateKey));
        return envelope;
    }

    /** The same envelope without its signature, which is what the signature is computed over. */
    public static ObjectNode unsigned(
            String eventId,
            String eventType,
            String merchantId,
            Instant occurredAt,
            ObjectNode payload,
            String causationId,
            String traceparent,
            String signingKeyId) {
        if (eventId == null || eventId.isBlank()) {
            throw new EnvelopeException("an event needs its own id before it can be signed");
        }
        if (merchantId == null || merchantId.isBlank()) {
            throw new EnvelopeException("a core event is scoped to a merchant");
        }
        if (signingKeyId == null || signingKeyId.isBlank()) {
            throw new EnvelopeException("an envelope carries the id of the key that signed it");
        }
        if (payload == null || !payload.isObject()) {
            throw new EnvelopeException("a core envelope's payload is a JSON object");
        }
        String producer = producerOf(eventType);
        String topic = topicFor(eventType, producer);

        ObjectNode envelope = MAPPER.createObjectNode();
        envelope.put("event_id", eventId);
        envelope.put("event_type", eventType);
        envelope.put("schema_version", 2);
        envelope.put("merchant_id", merchantId);
        // UTC with an explicit offset: a naive local timestamp is refused by the schema because ordering is
        // only meaningful across zones with the offset present (contracts/core/event-envelope.schema.json).
        envelope.put("occurred_at", occurredAt.toString());
        envelope.put("producer", producer);
        envelope.put("topic", topic);
        if (traceparent != null && !traceparent.isBlank()) {
            if (!traceparent.matches("^00-[a-f0-9]{32}-[a-f0-9]{16}-[a-f0-9]{2}$")) {
                throw new EnvelopeException("traceparent is not a W3C trace context: " + traceparent);
            }
            envelope.put("traceparent", traceparent);
        }
        if (causationId != null && !causationId.isBlank()) {
            envelope.put("causation_id", causationId);
        }
        envelope.set("payload", payload);
        envelope.put("signing_key_id", signingKeyId);
        return envelope;
    }

    /**
     * The producer an event type belongs to.
     *
     * <p>There is exactly one answer per type, so a caller cannot ask for a result "from case-service": the
     * schema pins producer and topic by event type, and a builder that let them be chosen independently would
     * be able to produce an envelope that no consumer's rule matches.
     */
    public static String producerOf(String eventType) {
        return switch (eventType) {
            case REFUND_REQUESTED -> CASE_SERVICE;
            case REFUND_SUCCEEDED, REFUND_FAILED, REFUND_UNKNOWN -> COMMERCE_SERVICE;
            default -> throw new EnvelopeException("not a core event type: " + eventType);
        };
    }

    /** The topic an event type is published on. */
    public static String topicFor(String eventType, String producer) {
        if (CASE_SERVICE.equals(producer)) {
            return CASE_TOPIC;
        }
        if (COMMERCE_SERVICE.equals(producer)) {
            return COMMERCE_TOPIC;
        }
        throw new EnvelopeException("not a core producer: " + producer);
    }

    /** The event type for a result state; UNKNOWN is a result, not a failure (docs/core-contracts.md:86). */
    public static String resultEventType(String state) {
        return switch (state) {
            case SUCCEEDED -> REFUND_SUCCEEDED;
            case FAILED -> REFUND_FAILED;
            case UNKNOWN -> REFUND_UNKNOWN;
            default -> throw new EnvelopeException("not a core refund result state: " + state);
        };
    }

    /**
     * The result payload, member for member with the envelope schema's {@code refundResult}.
     *
     * <p>The payload cannot know its own event type, so the state is a member and the envelope selects the
     * variant. {@code aggregate_version} is the operation's own optimistic-lock version: docs/domain-model.md:3
     * keeps it out of the envelope precisely so it has one home.
     */
    public static ObjectNode resultPayload(
            String operationId,
            String lineId,
            String state,
            long amountMinor,
            String providerRef,
            String reasonCode,
            long aggregateVersion) {
        if (!SUCCEEDED.equals(state) && !FAILED.equals(state) && !UNKNOWN.equals(state)) {
            throw new EnvelopeException("not a core refund result state: " + state);
        }
        ObjectNode payload = MAPPER.createObjectNode();
        payload.put("operation_id", operationId);
        payload.put("line_id", lineId);
        payload.put("state", state);
        payload.put("amount_minor", amountMinor);
        if (providerRef != null && !providerRef.isBlank()) {
            payload.put("provider_ref", providerRef);
        }
        if (reasonCode != null && !reasonCode.isBlank()) {
            payload.put("reason_code", reasonCode);
        }
        payload.put("aggregate_version", aggregateVersion);
        return payload;
    }

    /**
     * Verify an envelope's signature and return it, or raise.
     *
     * <p>Three checks, and each is a different attack: the producer's key must be one this service trusts
     * (docs/contracts.md:20), the signature must cover this envelope, and the event type must belong to the
     * producer that claims it. A verifier that skipped the last one would accept a result signed by
     * case-service's key.
     */
    public static ObjectNode verify(JsonNode envelope, PublicKey publicKey) {
        if (envelope == null || !envelope.isObject()) {
            throw new EnvelopeException("an event envelope is a JSON object");
        }
        JsonNode signature = envelope.get("signature");
        if (signature == null
                || !signature.isString()
                || signature.stringValue().isBlank()) {
            throw new EnvelopeException("a core envelope arrives signed");
        }
        JsonNode eventType = envelope.get("event_type");
        if (eventType == null || !eventType.isString()) {
            throw new EnvelopeException("a core envelope names its event type");
        }
        String expectedProducer = producerOf(eventType.stringValue());
        JsonNode producer = envelope.get("producer");
        if (producer == null || !producer.isString() || !expectedProducer.equals(producer.stringValue())) {
            throw new EnvelopeException(eventType.stringValue() + " does not come from "
                    + (producer == null ? "anyone" : producer.stringValue()));
        }
        String expectedTopic = topicFor(eventType.stringValue(), expectedProducer);
        JsonNode topic = envelope.get("topic");
        if (topic == null || !topic.isString() || !expectedTopic.equals(topic.stringValue())) {
            throw new EnvelopeException(eventType.stringValue() + " belongs on " + expectedTopic);
        }
        if (envelope.path("schema_version").asInt(0) != 2) {
            throw new EnvelopeException("this service speaks core schema_version 2");
        }
        CoreEventSignature.verify(envelope, signature.stringValue(), publicKey);
        return (ObjectNode) envelope;
    }

    /** A key id as it travels: opaque here, checked against a trust list by the consumer. */
    public static PrivateKey privateKeyFromPkcs8Base64(String base64) {
        return CoreEventSignature.privateKeyFromPkcs8(Base64.getDecoder().decode(base64.trim()));
    }

    /** The matching public key, as a producer or a verifier would hold it. */
    public static PublicKey publicKeyFromSpkiBase64(String base64) {
        return CoreEventSignature.publicKeyFromSpki(Base64.getDecoder().decode(base64.trim()));
    }

    /** The canonical form of an envelope, which is what two services must agree on byte for byte. */
    public static String canonical(JsonNode envelope) {
        return CanonicalJson.canonicalize(envelope);
    }

    /** UTF-8 bytes of {@link #canonical}, for a caller that hashes or compares envelopes. */
    public static byte[] canonicalBytes(JsonNode envelope) {
        return canonical(envelope).getBytes(StandardCharsets.UTF_8);
    }
}
