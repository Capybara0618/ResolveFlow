package com.resolveflow.commerce.messaging;

import com.resolveflow.commerce.refund.RefundCommand;
import com.resolveflow.commerce.refund.RefundError;
import com.resolveflow.commerce.refund.RefundOperationRepository;
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
 * Writing a core result event, signed, into the transaction that decided it (C05.2b, docs/domain-model.md:49).
 *
 * <p>The case side is waiting for exactly three answers — succeeded, failed, unknown — and this is the only
 * place that produces them. The signature is computed here rather than by the delivery loop, for the same two
 * reasons the command's is (C05.1a): it must cover the document the transaction produced, and the consumer must
 * be able to verify exactly the bytes that were published. {@link #writeRefundResult} is {@code @Transactional}
 * so a settlement joins it rather than starting a second transaction — the event and the settlement share a
 * commit or share a rollback, which is the property the outbox exists for.
 *
 * <p><b>What the payload says, member for member</b> (contracts/core event-envelope.schema.json, fixtures
 * valid.json): {@code operation_id}, {@code line_id}, {@code state}, {@code amount_minor},
 * {@code provider_ref} (null unless the provider named one), {@code reason_code} (null unless something
 * refused it) and {@code aggregate_version}, which is this operation row's own optimistic-lock version — the
 * contract gives that number exactly one home (contracts/core/README.md decision 5), and it is what lets the
 * case order a late {@code RefundUnknown} behind the {@code RefundSucceeded} that followed it instead of
 * believing whichever arrived last.
 *
 * <p><b>What the payload deliberately does not say.</b> A result reports one operation; the case correlates it
 * through {@code operation_id}, which it recorded when it sent the command (case_execution_command, C05.2a).
 * {@code causation_id} and {@code traceparent} are therefore left out rather than filled with something that
 * looks like a correlation and is not: this service does not store the command event's id on the operation row,
 * so any value here would be invented. Recording it is a real improvement and a change to the acceptance path,
 * not a line in this class.
 *
 * <p><b>Why the writing entry point is narrow.</b> The producer of an event is decided by its type
 * ({@link CoreEnvelope#producerOf}), so a generic "write any event" helper would let this service originate a
 * message claiming to come from the case — signed with this service's key. The only public entry point takes a
 * stored operation and derives everything else from it.
 */
@Service
public class ResultEventOutbox {

    private final ResultOutboxRepository outbox;
    private final Clock clock;
    private final ObjectMapper mapper;

    /** How the demo signing key is configured; a deployment mounts its own (docs/security-and-limits). */
    private final String signingKeyId;

    private final PrivateKey signingKey;

    public ResultEventOutbox(
            ResultOutboxRepository outbox,
            Clock clock,
            ObjectMapper mapper,
            @Value("${resolveflow.events.signing-key-id:commerce-service-demo-key}") String signingKeyId,
            @Value("${resolveflow.events.private-key-pkcs8-base64:}") String privateKeyBase64) {
        this.outbox = outbox;
        this.clock = clock;
        this.mapper = mapper;
        this.signingKeyId = signingKeyId;
        this.signingKey = loadSigningKey(privateKeyBase64);
    }

    /**
     * The producer's private key.
     *
     * <p>An empty setting falls back to the corpus fixture key, which exists so the whole flow can be run and
     * explained locally — the same position the JWT secret and the case side's signing key take. A deployment
     * supplies its own and rotates it; nothing here pretends the fixture key is a secret.
     */
    private static PrivateKey loadSigningKey(String configured) {
        if (configured == null || configured.isBlank()) {
            return CoreEnvelope.privateKeyFromPkcs8Base64(
                    com.resolveflow.shared.core.CoreFixtures.privateKeyPkcs8Base64());
        }
        return CoreEnvelope.privateKeyFromPkcs8Base64(configured);
    }

    /**
     * Sign and record the result event an operation's current state owes the case, returning the event id.
     *
     * @throws IllegalStateException if the operation is in a state that is not a result
     */
    @Transactional
    public String writeRefundResult(RefundOperationRepository.StoredOperation operation) {
        String eventType = eventTypeOf(operation.state());
        String eventId = UUID.randomUUID().toString();
        Instant now = Instant.now(clock);
        ObjectNode envelope = CoreEnvelope.sign(
                eventId,
                eventType,
                operation.merchantId(),
                now,
                payloadOf(operation),
                null,
                null,
                signingKeyId,
                signingKey);
        outbox.insert(
                eventId,
                eventType,
                envelope.path("schema_version").asInt(),
                operation.merchantId(),
                envelope.path("topic").asString(),
                envelope.path("producer").asString(),
                CoreEnvelope.canonical(envelope),
                envelope.path("signature").asString(),
                signingKeyId,
                now);
        return eventId;
    }

    /**
     * Record the answer a refused command is owed: a {@code RefundFailed} that names why (C05.3b).
     *
     * <p>Until this existed, a command the domain refused left one WARN line behind. The consumer's transaction
     * rolled back with the refusal and the transport acknowledged the delivery as terminal, so the command was
     * gone while the case — which had already written a row saying it sent one and consumed the authorisation —
     * waited in EXECUTING for an answer that could not come. The listener said so in a comment ("carrying the
     * refusal back to the case is C05.2's result projection"); this method is what that projection reads.
     *
     * <p>What keeps the entry point narrow: it answers a command that arrived, so it can still not originate a
     * message this service has no business signing. {@code operation_id}, {@code line_id} and
     * {@code amount_minor} come from that command — the document the case itself recorded in
     * {@code case_execution_command} — so the case correlates the answer through something it already knows.
     *
     * <p>{@code aggregate_version} is 1 because there is no operation row to version: this is the only fact
     * there will ever be about that operation id. A refusal is terminal, and trying again means a new command
     * under a new operation id (the case's authorisation was consumed), so nothing later needs ordering against
     * this.
     */
    @Transactional
    public String writeRefusedCommand(RefundCommand command, RefundError error) {
        String eventId = UUID.randomUUID().toString();
        Instant now = Instant.now(clock);
        ObjectNode payload = mapper.createObjectNode();
        payload.put("operation_id", command.operationId());
        payload.put("line_id", command.lineId());
        payload.put("state", CoreEnvelope.FAILED);
        payload.put("amount_minor", command.amountMinor());
        // Explicit nulls, for the same reason the settled payload has them: "no provider was ever named" is a
        // fact about this answer, and an omitted member would be a second, accidental contract.
        payload.putNull("provider_ref");
        payload.put("reason_code", error.name());
        payload.put("aggregate_version", 1);
        ObjectNode envelope = CoreEnvelope.sign(
                eventId,
                CoreEnvelope.REFUND_FAILED,
                command.merchantId(),
                now,
                payload,
                null,
                null,
                signingKeyId,
                signingKey);
        outbox.insert(
                eventId,
                CoreEnvelope.REFUND_FAILED,
                envelope.path("schema_version").asInt(),
                command.merchantId(),
                envelope.path("topic").asString(),
                envelope.path("producer").asString(),
                CoreEnvelope.canonical(envelope),
                envelope.path("signature").asString(),
                signingKeyId,
                now);
        return eventId;
    }

    /**
     * The event type for a state, refusing anything else.
     *
     * <p>The three result types are the contract's whole vocabulary (contracts/core/profile.json). A state
     * without a type is not "unknown, use the closest one": it would be an event the case cannot interpret, so
     * it is refused here — at the point where the mistake is still a bug rather than a signed document.
     */
    private static String eventTypeOf(String state) {
        return switch (state) {
            case CoreEnvelope.SUCCEEDED -> CoreEnvelope.REFUND_SUCCEEDED;
            case CoreEnvelope.FAILED -> CoreEnvelope.REFUND_FAILED;
            case CoreEnvelope.UNKNOWN -> CoreEnvelope.REFUND_UNKNOWN;
            default -> throw new IllegalStateException("operation state " + state + " is not a result event");
        };
    }

    /**
     * The result payload: all seven members, with explicit nulls where the fact is absent.
     *
     * <p>{@code null} rather than an omitted member, because the fixtures and the schema say so: "the provider
     * did not name a reference" is a fact about this result, and a reader that has to distinguish a missing
     * member from a null one would be reading a second, accidental contract.
     */
    private ObjectNode payloadOf(RefundOperationRepository.StoredOperation operation) {
        ObjectNode payload = mapper.createObjectNode();
        payload.put("operation_id", operation.operationId());
        payload.put("line_id", operation.lineId());
        payload.put("state", operation.state());
        payload.put("amount_minor", operation.amountMinor());
        payload.put("provider_ref", operation.providerRef());
        payload.put("reason_code", operation.reasonCode());
        payload.put("aggregate_version", operation.version());
        return payload;
    }
}
