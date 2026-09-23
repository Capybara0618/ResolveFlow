package com.resolveflow.caseservice.casefile;

import com.resolveflow.caseservice.outbox.EventOutbox;
import com.resolveflow.shared.contract.CanonicalJson;
import java.time.Clock;
import java.time.Instant;
import java.util.UUID;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import tools.jackson.databind.ObjectMapper;
import tools.jackson.databind.node.ObjectNode;

/**
 * Consuming an approved authorisation: the act that turns a human decision into a command (C05.2a).
 *
 * <p>This is the dispatch transaction docs/core-contracts.md:78 points at ("消费是C04派发事务的事"), and it is
 * <em>one</em> transaction because the four things it writes are one fact: the authorisation is spent, the case
 * is executing, the command exists, and the event that will carry it exists (docs/domain-model.md:36 "消费一次性
 * 创建…退款命令outbox", CI-05 "授权消费与操作/outbox原子"). Any subset of those committing alone is a story the
 * rest of the system can act on wrongly — a {@code CONSUMED} authorisation with no command is money a human
 * approved that can never be paid and that no retry can reach, and an event with no consumed row is a payment
 * whose approval still looks spendable.
 *
 * <p><b>Why this is not part of the approval.</b> The approval commits {@code APPROVED} and {@code AUTHORIZED}
 * and stops there (C03.3b), because "approved but not yet paid" is a real state: it can still be cancelled, and
 * a newer input revision retires it ({@code LiveAuthorization}). Merging the two would leave that state with
 * nowhere to live and would make the case view unable to say whether the money has moved. The price of the
 * separation is that something has to run this act, and that something is
 * {@link ExecutionDispatchLoop} — off unless asked for, and retried every tick, so an authorisation that could
 * not be consumed now is consumed later instead of being stranded.
 *
 * <p><b>The order of the checks is the order the facts can disagree.</b> The case row is locked first, because
 * every act that can retire an approval (new material, a verification, a proposal, a cancellation) takes that
 * lock as well, so the input cannot move under this transaction. The revision and hash checks below are then
 * statements about what <em>this service</em> fixed: if either fails, the command this service can rebuild is
 * not the one a human approved, and dispatching it would be paying an amount nobody approved. That is a defect
 * rather than an ordinary race — the revocation on input change is what normally prevents it — so it is
 * refused, loudly, and nothing is sent.
 */
@Service
public class AuthorizationConsumptionService {

    private final CaseRepository cases;
    private final AuthorizationRepository authorizations;
    private final ExecutionCommandRepository commands;
    private final EventOutbox outbox;
    private final Clock clock;
    private final ObjectMapper mapper;

    public AuthorizationConsumptionService(
            CaseRepository cases,
            AuthorizationRepository authorizations,
            ExecutionCommandRepository commands,
            EventOutbox outbox,
            Clock clock,
            ObjectMapper mapper) {
        this.cases = cases;
        this.authorizations = authorizations;
        this.commands = commands;
        this.outbox = outbox;
        this.clock = clock;
        this.mapper = mapper;
    }

    /**
     * What one consumption attempt did.
     *
     * <p>{@code skippedBecause} is not an error channel: an authorisation that is no longer approved, or whose
     * case is no longer authorised, is the loop catching up with a decision somebody else already made
     * (another instance consumed it, or the case was cancelled). It is reported rather than thrown so the
     * caller can count it and an operator can read why nothing was sent.
     */
    public record Consumption(String authorizationId, String operationId, String eventId, String skippedBecause) {

        public boolean dispatched() {
            return skippedBecause == null;
        }

        static Consumption skipped(String authorizationId, String why) {
            return new Consumption(authorizationId, null, null, why);
        }
    }

    /**
     * Spend one approved authorisation: case {@code AUTHORIZED → EXECUTING}, authorisation
     * {@code APPROVED → CONSUMED}, the signed command in the outbox, and the row that records it — all in this
     * transaction.
     */
    @Transactional
    public Consumption consume(AuthorizationRepository.DispatchCandidate candidate) {
        String authorizationId = candidate.authorizationId();
        CaseRow row = cases.findCaseForUpdate(candidate.caseId());
        if (row == null) {
            throw new CaseStateConflictException("case " + candidate.caseId() + " no longer exists");
        }
        AuthorizationRepository.StoredAuthorization stored = authorizations.findByAuthorizationId(authorizationId);
        if (stored == null) {
            throw new CaseStateConflictException("authorisation " + authorizationId + " no longer exists");
        }
        if (stored.authorizationStatus() != AuthorizationStatus.APPROVED) {
            return Consumption.skipped(
                    authorizationId, "the authorisation is " + stored.authorizationStatus() + ", not APPROVED");
        }
        if (row.status() != CaseStatus.AUTHORIZED) {
            return Consumption.skipped(authorizationId, "the case is " + row.status() + ", not AUTHORIZED");
        }
        if (stored.inputRevision() != row.inputRevision()) {
            return Consumption.skipped(
                    authorizationId,
                    "the authorisation fixed input revision " + stored.inputRevision() + " but the case is at "
                            + row.inputRevision() + ", so what it would execute is not what it approved");
        }

        RefundCommand command = RefundCommand.fixedBy(stored, row);
        String payloadHash = command.payloadHash(mapper);
        if (!payloadHash.equals(stored.payloadHash())) {
            return Consumption.skipped(
                    authorizationId,
                    "the command this service can rebuild hashes to " + payloadHash + " instead of the fixed "
                            + stored.payloadHash() + ", so nothing that was approved could be sent");
        }

        Instant now = Instant.now(clock);
        // The expected status is part of each UPDATE, so both transitions are conditional in the database and
        // not only in the checks above: a decision or a cancellation arriving with this one cannot both win.
        if (cases.transition(row.caseId(), CaseStatus.AUTHORIZED.name(), CaseStatus.EXECUTING.name(), now) != 1) {
            throw new CaseStateConflictException("case " + row.caseId()
                    + " moved while its authorisation was being consumed; nothing was" + " dispatched");
        }
        if (authorizations.consume(authorizationId, stored.authorizationVersion(), now) != 1) {
            throw new CaseStateConflictException("authorisation " + authorizationId
                    + " was decided while it was being consumed; nothing was dispatched");
        }
        // Signed and stored inside this transaction (EventOutbox), so the envelope that leaves is the one this
        // transaction decided, and the delivery loop can only ever send that document.
        String eventId =
                outbox.writeRefundCommand(row.caseId(), authorizationId, row.merchantId(), command, newTraceparent());
        if (commands.insert(
                        authorizationId,
                        row.caseId(),
                        stored.plannedOperationId(),
                        eventId,
                        stored.inputRevision(),
                        now)
                != 1) {
            throw new CaseStateConflictException(
                    "authorisation " + authorizationId + " already has a command; nothing was dispatched");
        }
        cases.insertTimeline(
                row.caseId(),
                UUID.randomUUID().toString(),
                cases.nextTimelineSequence(row.caseId()),
                TimelineEventType.EXECUTION_UPDATED.name(),
                dispatchDetail(stored, eventId, payloadHash),
                now,
                row.inputRevision());

        return new Consumption(authorizationId, stored.plannedOperationId(), eventId, null);
    }

    /**
     * What the trajectory row says about the dispatch.
     *
     * <p>{@code EXECUTION_UPDATED} is the contract's type for this ("the rest belong to the steps that produce
     * them", TimelineEventType), and the detail carries the two ids a reader needs next: the operation Commerce
     * will record, and the event id whose later fate the result events (C05.2b) will name. The amount is here
     * because this row is what a person reads to answer "how much did we just send" without joining three
     * tables.
     */
    private String dispatchDetail(
            AuthorizationRepository.StoredAuthorization stored, String eventId, String payloadHash) {
        ObjectNode detail = mapper.createObjectNode();
        detail.put("authorization_id", stored.authorizationId());
        detail.put("operation_id", stored.plannedOperationId());
        detail.put("event_id", eventId);
        detail.put("payload_hash", payloadHash);
        detail.put("amount_minor", stored.amountMinor());
        detail.put("currency", stored.currency());
        detail.put("case_status", CaseStatus.EXECUTING.name());
        return CanonicalJson.canonicalize(detail);
    }

    /**
     * A W3C trace context for the command this dispatch originates.
     *
     * <p>Nothing is being continued here — a scheduled pass has no incoming trace — so this is the start of
     * one, which is what a tracer does for an outbound message. The envelope accepts a missing traceparent, and
     * sending none would be simpler; it is sent because the result events that come back name their cause, and
     * a value that exists on both sides is what makes the two readable together (C05.2b).
     */
    private static String newTraceparent() {
        String traceId = UUID.randomUUID().toString().replace("-", "");
        String spanId = UUID.randomUUID().toString().replace("-", "").substring(0, 16);
        return "00-" + traceId + "-" + spanId + "-01";
    }
}
