package com.resolveflow.caseservice.result;

import com.resolveflow.caseservice.casefile.CaseRepository;
import com.resolveflow.caseservice.casefile.CaseRow;
import com.resolveflow.caseservice.casefile.CaseStatus;
import com.resolveflow.caseservice.casefile.ExecutionCommandRepository;
import com.resolveflow.caseservice.casefile.TimelineEventType;
import com.resolveflow.shared.core.CoreEnvelope;
import java.time.Clock;
import java.time.Instant;
import java.util.UUID;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import tools.jackson.databind.JsonNode;
import tools.jackson.databind.ObjectMapper;
import tools.jackson.databind.node.ObjectNode;

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
        String expectedType;
        try {
            expectedType = CoreEnvelope.resultEventType(state);
        } catch (CoreEnvelope.EnvelopeException notAState) {
            // A trusted producer can still send a state this version does not know (a newer Commerce, or a bug).
            // Letting the shared helper's exception escape would roll the transaction back *without* a rejection
            // row, and a message that is retried forever with no operator-visible record is the one outcome this
            // consumer is built to avoid.
            refusal(
                    CaseResultVerifier.Refusal.MALFORMED,
                    "the payload's state is not a core refund result state: " + state,
                    verified,
                    rawMessage);
            return null;
        }
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
                // The verified document, canonically serialised: not the transport's exact bytes (key order and
                // whitespace are normalised), but a form whose signature still verifies, so the verification is
                // reproducible later. V13's comment says "verbatim"; that wording is wrong and is left alone there
                // because a migration's text is checksummed once applied — the correction lives here.
                CoreEnvelope.canonical(verified),
                requiredText(verified, "signature", verified, rawMessage),
                requiredText(verified, "signing_key_id", verified, rawMessage),
                Instant.now(clock));
        if (claimed == 2) {
            LOG.info("result {} for case {} was delivered again; the first delivery stands", eventId, row.caseId());
            return Disposition.DUPLICATE;
        }
        if (claimed != 1) {
            // 2 is the duplicate answer above. Anything else means the claim statement did not do what it says,
            // which is worth refusing rather than treating as a claim: since V14 the duplicate branch always
            // changes `deliveries`, so 0 can no longer happen either.
            throw new IllegalStateException("claiming result " + eventId + " affected " + claimed
                    + " rows, so it is neither claimed nor a duplicate");
        }

        // C05.2b-3b: applying the outcome is the second half of this same transaction
        // (docs/core-contracts.md:86), so the inbox row that claims the result and the case that changes because
        // of it cannot disagree — and a crash between them is not a state the database can hold.
        if (applyToCase(row, payload, state, operationId, lineId, amountMinor, eventId)) {
            inbox.markProjected(CaseResultTrustConfiguration.RESULT_CONSUMER, eventId, Instant.now(clock));
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
     * Apply one accepted outcome to the case (C05.2b-3b, docs/domain-model.md:55).
     *
     * <p>Slices ① and ② are here: {@code EXECUTING -> CLOSED_SUCCESS} for a successful refund, and
     * {@code EXECUTING -> PENDING_REVIEW} for a determined failure whose money Commerce has already released.
     * The target status decides the trajectory kind too — a terminal target is the contract's {@code CASE_CLOSED},
     * anything else is {@code EXECUTION_UPDATED} — so neither a status nor a kind is invented: the migration's
     * CHECK constraints already hold every value used here.
     *
     * <p>An unknown answer ({@code -> RECONCILING}) is slice ③. Until it lands, a result whose state has no target
     * is still claimed and recorded, and is deliberately left with {@code projected_at} NULL — the marker that
     * says "claimed, not yet applied". That is the honest interim: the row is visibly outstanding, instead of
     * being marked applied while the case does not move.
     *
     * @return whether the case was actually moved, so the caller only marks the row applied when it was
     */
    private boolean applyToCase(
            CaseRow row,
            JsonNode payload,
            String state,
            String operationId,
            String lineId,
            long amountMinor,
            String eventId) {
        CaseStatus target = targetStatus(state);
        if (target == null) {
            LOG.info(
                    "result {} says {}; projecting that outcome is a later slice of C05.2b-3b, so case {} keeps"
                            + " its status and the inbox row stays unapplied",
                    eventId,
                    state,
                    row.caseId());
            return false;
        }
        Instant now = Instant.now(clock);
        if (cases.transition(row.caseId(), row.status().name(), target.name(), now) != 1) {
            // The expected status is in the statement, so this means the case was not EXECUTING when the result
            // arrived. Which delivery may move it, and in what order, is exactly slice ④ (ordering by
            // aggregate_version); leaving the row unapplied keeps that decision open instead of guessing here.
            LOG.warn(
                    "case {} was {} when result {} arrived, so nothing was projected and the row stays unapplied",
                    row.caseId(),
                    row.status(),
                    eventId);
            return false;
        }
        cases.insertTimeline(
                row.caseId(),
                UUID.randomUUID().toString(),
                cases.nextTimelineSequence(row.caseId()),
                timelineKindFor(target),
                outcomeDetail(row, payload, eventId, operationId, lineId, amountMinor, state, target),
                now,
                row.inputRevision());
        return true;
    }

    /**
     * Which status an outcome moves the case to, or {@code null} while that outcome's projection is a later slice.
     *
     * <p>docs/domain-model.md:55: a success closes the case; a <em>determined</em> failure sends it back to a
     * person, because the money is released and going again needs a new authorisation; and an unknown answer parks
     * it in {@code RECONCILING}, because "we do not know" releases nothing and settles nothing — the money may
     * still move, so the input stays frozen (docs/domain-model.md:36) until somebody finds out what happened.
     *
     * <p>{@code null} therefore does not mean "an outcome we reject" but "an outcome this step does not project":
     * a state this version cannot place is still claimed in the inbox and left visibly unapplied, rather than
     * being silently marked applied while the case stands still.
     */
    private static CaseStatus targetStatus(String state) {
        if (CoreEnvelope.SUCCEEDED.equals(state)) {
            return CaseStatus.CLOSED_SUCCESS;
        }
        if (CoreEnvelope.FAILED.equals(state)) {
            return CaseStatus.PENDING_REVIEW;
        }
        if (CoreEnvelope.UNKNOWN.equals(state)) {
            return CaseStatus.RECONCILING;
        }
        return null;
    }

    /**
     * The trajectory kind for a target status: the contract's only terminal event type for a close, and its
     * general "execution moved" type for everything else (TimelineEventType). It is derived from the status rather
     * than listed per outcome, which is also why slice ③'s {@code RECONCILING} arrived with no new kind at all.
     */
    private static String timelineKindFor(CaseStatus target) {
        return target.isTerminal() ? TimelineEventType.CASE_CLOSED.name() : TimelineEventType.EXECUTION_UPDATED.name();
    }

    /**
     * What the trajectory row says about the outcome.
     *
     * <p>{@code CASE_CLOSED} is the contract's only terminal event type, so the status and the outcome that caused
     * it are written into the detail rather than into the kind (the same reasoning the cancellation path states
     * for its own terminal row). The operation, the line and the amount are here because this row is what a person
     * reads to answer "which refund moved this case, and for how much" without joining three tables; the reason
     * code is here because whoever is looking at a case sent back to review needs Commerce's word for why.
     */
    private String outcomeDetail(
            CaseRow row,
            JsonNode payload,
            String eventId,
            String operationId,
            String lineId,
            long amountMinor,
            String state,
            CaseStatus target) {
        ObjectNode detail = mapper.createObjectNode();
        detail.put("case_status", target.name());
        detail.put("outcome", state);
        detail.put("operation_id", operationId);
        detail.put("event_id", eventId);
        detail.put("line_id", lineId);
        detail.put("amount_minor", amountMinor);
        String reasonCode = optionalText(payload, "reason_code");
        if (reasonCode != null) {
            detail.put("reason_code", reasonCode);
        }
        detail.put("case_id", row.caseId());
        return detail.toString();
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
