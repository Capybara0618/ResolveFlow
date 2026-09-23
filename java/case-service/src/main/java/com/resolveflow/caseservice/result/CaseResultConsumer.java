package com.resolveflow.caseservice.result;

import com.resolveflow.caseservice.casefile.CaseRepository;
import com.resolveflow.caseservice.casefile.CaseRow;
import com.resolveflow.caseservice.casefile.ExecutionCommandRepository;
import com.resolveflow.shared.core.CoreEnvelope;
import java.time.Clock;
import java.time.Instant;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import tools.jackson.databind.JsonNode;
import tools.jackson.databind.ObjectMapper;

/**
 * Consuming one signed refund result (C05.2b-3a, docs/core-contracts.md:86, docs/domain-model.md:55).
 *
 * <p>The order inside {@link #consume} is the design, and it is the mirror of Commerce's
 * {@code RefundCommandConsumer}:
 *
 * <ol>
 *   <li><b>Parse.</b> A message that is not JSON is refused and recorded; there is nothing to verify.
 *   <li><b>Verify.</b> Signature and signer, before anything is trusted: the payload is only read as a result
 *       once it is known to have come from Commerce (the trust map decides that, not the maths alone).
 *   <li><b>Resolve the case.</b> The message names an operation, and this service owns the
 *       operation-to-case mapping ({@code case_execution_command}, written when the command was dispatched), so
 *       the case is looked up rather than taken from the message. A result for an operation this service never
 *       issued cannot be filed anywhere, and is refused loudly instead of being attached to the nearest case.
 *   <li><b>Check the scope.</b> The result has to be about the case's own merchant and line. This is the
 *       cross-tenant check the contract asks for ("Case验证来源及签名"): a genuine, correctly signed result for
 *       another merchant's case is still not a fact about this one.
 *   <li><b>Claim the event id.</b> The inbox insert is the claim, in the same transaction as the fact it
 *       records. A redelivery does not raise: the claim tells this consumer it was a duplicate, and the
 *       delivery ends as an idempotent no-op that says so.
 *   <li><b>Store the fact.</b> The payload members and the signed bytes are written next to the claim, so the
 *       verification is reproducible and the projection (C05.2b-3b) has everything it needs.
 * </ol>
 *
 * <p><b>What this deliberately does not do.</b> It does not touch the case's status, its version or its
 * timeline. Receiving a result and projecting it onto the state machine
 * ({@code UNKNOWN -> RECONCILING}, success {@code -> CLOSED_SUCCESS}, definitive failure {@code -> PENDING_REVIEW})
 * is C05.2b-3b, which will read the inbox rows this transaction leaves behind and consume
 * {@code projected_at}. This sub-step ends with the fact durably stored and the case exactly where it was, and
 * its test asserts that boundary rather than pretending the projection happened.
 */
@Service
public class CaseResultConsumer {

    private static final Logger LOG = LoggerFactory.getLogger(CaseResultConsumer.class);

    /** What one delivery was, once the transport has handed it to a consumer. */
    public enum Disposition {
        /** The result was new and is now durably recorded. */
        ACCEPTED,
        /** This event id was already claimed: a duplicate, and harmless. */
        DUPLICATE
    }

    private final CaseResultInboxRepository inbox;
    private final CaseResultVerifier verifier;
    private final CaseResultRejectionLog rejections;
    private final ExecutionCommandRepository commands;
    private final CaseRepository cases;
    private final Clock clock;
    private final ObjectMapper mapper;

    public CaseResultConsumer(
            CaseResultInboxRepository inbox,
            CaseResultVerifier verifier,
            CaseResultRejectionLog rejections,
            ExecutionCommandRepository commands,
            CaseRepository cases,
            Clock clock,
            ObjectMapper mapper) {
        this.inbox = inbox;
        this.verifier = verifier;
        this.rejections = rejections;
        this.commands = commands;
        this.cases = cases;
        this.clock = clock;
        this.mapper = mapper;
    }

    /**
     * Consume one message.
     *
     * @param rawMessage the exact text the transport delivered
     */
    @Transactional
    public Disposition consume(String rawMessage) {
        JsonNode envelope = parse(rawMessage);
        JsonNode verified;
        try {
            verified = verifier.verify(envelope);
        } catch (CaseResultVerifier.RefusedEventException refused) {
            reject(refused.refusal(), refused, envelope, rawMessage);
            throw refused;
        }

        String eventId = requiredText(verified, "event_id", verified, rawMessage);
        String eventType = requiredText(verified, "event_type", verified, rawMessage);
        String merchantId = requiredText(verified, "merchant_id", verified, rawMessage);
        if (CoreEnvelope.producerOf(eventType) != CoreEnvelope.COMMERCE_SERVICE) {
            // The consumer is subscribed to the result topic, so a command arriving here means a routing or
            // subscription mistake. Filed as if it were a result it would report an outcome for an operation
            // nobody asked Commerce to perform.
            refusal(
                    CaseResultVerifier.Refusal.WRONG_DIRECTION,
                    "this consumer executes results, not " + eventType,
                    verified,
                    rawMessage);
        }

        JsonNode payload = verified.get("payload");
        if (payload == null || !payload.isObject()) {
            refusal(CaseResultVerifier.Refusal.MALFORMED, "a refund result has a payload object", verified, rawMessage);
        }
        String operationId = requiredText(payload, "operation_id", verified, rawMessage);
        String lineId = requiredText(payload, "line_id", verified, rawMessage);
        String state = requiredText(payload, "state", verified, rawMessage);
        // The envelope's event type and the payload's state are two spellings of one fact; a document where
        // they disagree is a broken producer, and guessing which half is right is how a FAILED gets recorded as
        // a SUCCEEDED.
        String expectedType = CoreEnvelope.resultEventType(state);
        if (!expectedType.equals(eventType)) {
            refusal(
                    CaseResultVerifier.Refusal.MALFORMED,
                    "the envelope says " + eventType + " but its payload says " + state,
                    verified,
                    rawMessage);
        }
        long amountMinor = requiredLong(payload, "amount_minor", verified, rawMessage);
        long aggregateVersion = requiredLong(payload, "aggregate_version", verified, rawMessage);

        // The case is resolved from this service's own record of the operation, never from the message.
        ExecutionCommandRepository.StoredCommand command = commandFor(operationId, verified, rawMessage);
        CaseRow row = cases.findCase(command.caseId());
        if (row == null) {
            refusal(
                    CaseResultVerifier.Refusal.UNKNOWN_OPERATION,
                    "operation " + operationId + " names case " + command.caseId() + ", which no longer exists",
                    verified,
                    rawMessage);
        }
        if (!row.merchantId().equals(merchantId)) {
            refusal(
                    CaseResultVerifier.Refusal.WRONG_MERCHANT,
                    "the result is scoped to " + merchantId + " but case " + row.caseId() + " belongs to "
                            + row.merchantId(),
                    verified,
                    rawMessage);
        }
        if (!row.lineId().equals(lineId)) {
            refusal(
                    CaseResultVerifier.Refusal.LINE_MISMATCH,
                    "the result names line " + lineId + " but case " + row.caseId() + " covers " + row.lineId(),
                    verified,
                    rawMessage);
        }

        // The claim: one row per (consumer, event). 1 means this delivery claimed it, 2 means it was already
        // claimed — the duplicate answer, decided by the primary key rather than by a check that a race could
        // pass. Only `detail` is touched on a duplicate, so the payload the first delivery recorded stands.
        int claimed = inbox.claim(
                CaseResultTrustConfiguration.RESULT_CONSUMER,
                eventId,
                eventType,
                verified.path("schema_version").asInt(),
                merchantId,
                row.caseId(),
                operationId,
                lineId,
                state,
                amountMinor,
                optionalText(payload, "provider_ref"),
                optionalText(payload, "reason_code"),
                aggregateVersion,
                // The signed bytes are stored exactly as they arrived, which is what makes the verification
                // reproducible later; the signature column is the same value the envelope already carries, kept
                // separately so an operator can see at a glance that a row is signed.
                CoreEnvelope.canonical(verified),
                requiredText(verified, "signature", verified, rawMessage),
                requiredText(verified, "signing_key_id", verified, rawMessage),
                Instant.now(clock));
        if (claimed == 2) {
            LOG.info("result {} for case {} was delivered again; the first delivery stands", eventId, row.caseId());
            return Disposition.DUPLICATE;
        }
        if (claimed != 1) {
            // MySQL reports 0 only when the duplicate branch changed nothing, which cannot happen while the
            // statement always writes the same duplicate sentence. Anything but 1 or 2 is therefore a surprise
            // worth refusing rather than treating as a claim.
            throw new IllegalStateException("claiming result " + eventId + " affected " + claimed
                    + " rows, so it is neither claimed nor a duplicate");
        }

        LOG.info(
                "result {} for case {} recorded: operation {} is {} at Commerce version {}",
                eventId,
                row.caseId(),
                operationId,
                state,
                aggregateVersion);
        return Disposition.ACCEPTED;
    }

    /**
     * The command this service issued for an operation, or a refusal.
     *
     * <p>A result that names an operation with no command behind it is refused rather than filed: this service
     * cannot know which case it concerns, and inventing one would be worse than refusing. The lookup is by
     * operation because that is what the message carries — the payload deliberately has no {@code case_id}
     * (contracts/core/event-envelope.schema.json, {@code refundResult}).
     */
    private ExecutionCommandRepository.StoredCommand commandFor(
            String operationId, JsonNode envelope, String rawMessage) {
        ExecutionCommandRepository.StoredCommand command = commands.findByOperationId(operationId);
        if (command == null) {
            refusal(
                    CaseResultVerifier.Refusal.UNKNOWN_OPERATION,
                    "operation " + operationId + " was never issued a command by this service",
                    envelope,
                    rawMessage);
        }
        return command;
    }

    private JsonNode parse(String rawMessage) {
        if (rawMessage == null || rawMessage.isBlank()) {
            refusal(CaseResultVerifier.Refusal.MALFORMED, "an empty message is not an event", null, rawMessage);
        }
        try {
            return mapper.readTree(rawMessage);
        } catch (RuntimeException notJson) {
            refusal(
                    CaseResultVerifier.Refusal.MALFORMED,
                    "the message is not JSON: " + notJson.getMessage(),
                    null,
                    rawMessage);
            return null;
        }
    }

    /** Refuse and file, then raise: the row is what an operator reads, the failure is what the transport sees. */
    private void refusal(CaseResultVerifier.Refusal refusal, String detail, JsonNode envelope, String rawMessage) {
        CaseResultVerifier.RefusedEventException refused =
                new CaseResultVerifier.RefusedEventException(refusal, detail);
        reject(refusal, refused, envelope, rawMessage);
        throw refused;
    }

    /** Keep the refused message and why, in its own transaction so the consumer's rollback cannot erase it. */
    private void reject(
            CaseResultVerifier.Refusal refusal, RuntimeException cause, JsonNode envelope, String rawMessage) {
        rejections.record(
                CaseResultTrustConfiguration.RESULT_CONSUMER, refusal, envelope, rawMessage, cause.getMessage());
        LOG.warn("refused a core result: {} ({})", refusal.name(), cause.getMessage());
    }

    private String requiredText(JsonNode node, String member, JsonNode envelope, String rawMessage) {
        JsonNode value = node.get(member);
        if (value == null || !value.isString() || value.stringValue().isBlank()) {
            refusal(CaseResultVerifier.Refusal.MALFORMED, "the result has no usable " + member, envelope, rawMessage);
        }
        return value.stringValue();
    }

    private static String optionalText(JsonNode node, String member) {
        JsonNode value = node.get(member);
        return value == null || !value.isString() || value.stringValue().isBlank() ? null : value.stringValue();
    }

    private long requiredLong(JsonNode payload, String member, JsonNode envelope, String rawMessage) {
        JsonNode value = payload.get(member);
        if (value == null || !value.isNumber()) {
            refusal(
                    CaseResultVerifier.Refusal.MALFORMED,
                    "the result payload has no usable " + member,
                    envelope,
                    rawMessage);
        }
        return value.asLong();
    }
}
