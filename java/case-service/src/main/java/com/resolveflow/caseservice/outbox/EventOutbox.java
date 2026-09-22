package com.resolveflow.caseservice.outbox;

import com.resolveflow.caseservice.casefile.RefundCommand;
import com.resolveflow.shared.core.CoreEnvelope;
import java.security.PrivateKey;
import java.time.Clock;
import java.time.Instant;
import java.util.UUID;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import tools.jackson.databind.ObjectMapper;
import tools.jackson.databind.node.ObjectNode;

/**
 * Writing a core event, signed, into the transaction that decided it (docs/domain-model.md:45).
 *
 * <p>The signature is computed here rather than by the delivery loop, and stored with the envelope. Two
 * reasons, and both are about what a signature means: it must cover the document the transaction produced
 * (not whatever the code renders later), and the consumer must be able to verify exactly the bytes that were
 * published. Re-signing at send time would make the stored row an approximation of the message.
 *
 * <p>{@link #write} is {@code @Transactional} so a caller inside a business transaction joins it rather than
 * starting a second one: the event and the effect share a commit or share a rollback, which is the property
 * the outbox exists for.
 */
@Service
public class EventOutbox {

    /** How the demo signing key is configured; a deployment mounts its own (docs/security-and-limits). */
    private final String signingKeyId;

    private final PrivateKey signingKey;
    private final OutboxRepository outbox;
    private final Clock clock;
    private final ObjectMapper mapper;

    public EventOutbox(
            OutboxRepository outbox,
            Clock clock,
            ObjectMapper mapper,
            @Value("${resolveflow.events.signing-key-id:case-service-demo-key}") String signingKeyId,
            @Value("${resolveflow.events.private-key-pkcs8-base64:}") String privateKeyBase64) {
        this.outbox = outbox;
        this.clock = clock;
        this.mapper = mapper;
        this.signingKeyId = signingKeyId;
        this.signingKey = loadSigningKey(privateKeyBase64);
    }

    /**
     * The private key events are signed with.
     *
     * <p>An empty setting falls back to the corpus fixture key, which exists so the whole flow can be run and
     * explained locally (the same position case-service's JWT secret takes). A deployment supplies its own
     * and rotates it; nothing here pretends the fixture key is a secret.
     */
    private static PrivateKey loadSigningKey(String configured) {
        if (configured == null || configured.isBlank()) {
            return CoreEnvelope.privateKeyFromPkcs8Base64(
                    com.resolveflow.shared.core.CoreFixtures.privateKeyPkcs8Base64());
        }
        return CoreEnvelope.privateKeyFromPkcs8Base64(configured);
    }

    /**
     * Sign and record one core event, returning the id it was written under.
     *
     * <p><b>Private on purpose.</b> The producer of an event is decided by its type
     * ({@link CoreEnvelope#producerOf}), so a service that can call a generic "write any event" helper can
     * originate a message that claims to come from the other service — and this service's key would sign it.
     * Each direction therefore gets its own named entry point, and the only one that exists here is the
     * command.
     */
    private String write(
            String eventType, String merchantId, ObjectNode payload, String causationId, String traceparent) {
        String eventId = UUID.randomUUID().toString();
        Instant now = Instant.now(clock);
        ObjectNode envelope = CoreEnvelope.sign(
                eventId, eventType, merchantId, now, payload, causationId, traceparent, signingKeyId, signingKey);
        outbox.insert(
                eventId,
                eventType,
                envelope.path("schema_version").asInt(),
                merchantId,
                envelope.path("topic").asString(),
                envelope.path("producer").asString(),
                CoreEnvelope.canonical(envelope),
                envelope.path("signature").asString(),
                signingKeyId,
                "PENDING",
                now);
        return eventId;
    }

    /**
     * Sign and record the refund command an approved authorisation fixes, returning the event id.
     *
     * <p>This is the one place the command's shape is assembled on the sending side. Callers pass the fields
     * they own and get back an id; they cannot hand in a free-form payload, because the command has to carry
     * exactly the twelve members the authorisation hashed (docs/core-contracts.md:19) — a command assembled
     * ad hoc is one whose hash the consumer will refuse, correctly.
     *
     * <p>{@code merchantId} is repeated here rather than read back from the case: the envelope is scoped to
     * the merchant, and the caller already has it from the row it locked.
     */
    @Transactional
    public String writeRefundCommand(
            String caseId, String authorizationId, String merchantId, RefundCommand command, String traceparent) {
        // The document carries the hash as a member (contracts/core/refund-command.schema.json requires all
        // thirteen), and the consumer re-derives it: a command whose hash does not cover its own members is
        // refused there, which is the check that keeps "what was approved" and "what is executed" one object.
        ObjectNode document = command.toJson(mapper);
        document.put("payload_hash", command.payloadHash(mapper));
        return write(CoreEnvelope.REFUND_REQUESTED, merchantId, document, authorizationId, traceparent);
    }

    /** The stored envelope as a tree, for a caller that wants to show or forward it. */
    public ObjectNode envelopeOf(String eventId) {
        OutboxEvent event = outbox.find(eventId);
        if (event == null) {
            throw new IllegalArgumentException("no outbox event " + eventId);
        }
        return (ObjectNode) mapper.readTree(event.envelope());
    }
}
