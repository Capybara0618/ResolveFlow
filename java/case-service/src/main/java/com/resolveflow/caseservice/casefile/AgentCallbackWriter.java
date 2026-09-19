package com.resolveflow.caseservice.casefile;

import com.resolveflow.shared.contract.CanonicalJson;
import java.time.Clock;
import java.time.Instant;
import java.util.List;
import java.util.UUID;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import tools.jackson.databind.ObjectMapper;
import tools.jackson.databind.node.ArrayNode;
import tools.jackson.databind.node.ObjectNode;

/**
 * Applying one delivery, under the case's row lock, in one transaction with its inbox row.
 *
 * <p>The order inside the transaction is the design:
 *
 * <ol>
 *   <li>Lock and read the case. Everything the disposition depends on — the current revision and whether the
 *       case has moved past the run — is read here, not before, so a revision that moved a moment ago cannot
 *       be applied to.
 *   <li>Insert the inbox row. That insert is the claim on the callback id, and it happens before any effect,
 *       so a redelivery that races the first one fails on the primary key and rolls back having changed
 *       nothing.
 *   <li>Apply the effect: at most one status transition, exactly one trajectory row, one version bump.
 * </ol>
 *
 * <p>STALE is written to the inbox like ACCEPTED, because "this delivery arrived and did not apply" is
 * exactly the fact the record exists for; DUPLICATE is not, because it describes a delivery that is already
 * in the record (docs/core-contracts.md:59).
 */
@Service
public class AgentCallbackWriter {

    /**
     * Statuses in which the run no longer owns the case.
     *
     * <p>Deliberately not {@code isTerminal()} plus a list of wishes: pending review means a human is looking
     * at it, and authorized/executing/reconciling mean the case has moved past the run's proposal. In all of
     * them a further delivery from the run is stale rather than applicable — which is the contract's "after a
     * human takes over, STALE and no retry" (docs/core-contracts.md:59).
     */
    private static final List<CaseStatus> RUN_HANDED_OVER =
            List.of(CaseStatus.PENDING_REVIEW, CaseStatus.AUTHORIZED, CaseStatus.EXECUTING, CaseStatus.RECONCILING);

    private final CaseRepository cases;
    private final AgentCallbackRepository inbox;
    private final Clock clock;
    private final ObjectMapper mapper;

    public AgentCallbackWriter(CaseRepository cases, AgentCallbackRepository inbox, Clock clock, ObjectMapper mapper) {
        this.cases = cases;
        this.inbox = inbox;
        this.clock = clock;
        this.mapper = mapper;
    }

    @Transactional
    public AgentCallbackService.Receipt apply(String caseId, AgentCallback callback, String payloadHash) {
        CaseRow row = cases.findCaseForUpdate(caseId);
        if (row == null) {
            throw new CaseReadService.CaseNotVisibleException();
        }
        Instant now = Instant.now(clock);

        String staleReason = staleReason(row, callback);
        if (staleReason != null) {
            claim(caseId, callback, payloadHash, AgentCallback.Disposition.STALE, now);
            return new AgentCallbackService.Receipt(AgentCallback.Disposition.STALE, null, staleReason);
        }

        // The payload is read and checked before anything is written, so a malformed delivery cannot leave a
        // status transition behind that is rolled back a moment later.
        Payload payload = parse(callback);
        CaseStatus next =
                switch (callback.kind()) {
                    case STARTED -> startedStatus(row, callback);
                    case QUESTION -> questionStatus(row, callback, payload.questions());
                    case FAILED -> failureStatus(row, callback, payload.failure());
                    case PROPOSAL -> throw proposalsAreNotAcceptedYet();
                };

        // The claim goes in before the effect, so a losing race cannot leave an effect behind.
        claim(caseId, callback, payloadHash, AgentCallback.Disposition.ACCEPTED, now);
        if (cases.transition(caseId, row.status().name(), next.name(), now) != 1) {
            // Unreachable while the row lock is held; kept because silently returning a version nobody
            // advanced would make the response a claim about a write that did not happen.
            throw new CaseStateConflictException(
                    "this case is no longer in " + row.status() + "; the delivery was not applied");
        }
        cases.insertTimeline(
                caseId,
                UUID.randomUUID().toString(),
                nextSequence(caseId),
                eventType(callback.kind()).name(),
                detail(callback, payload),
                now,
                callback.inputRevision());
        return new AgentCallbackService.Receipt(AgentCallback.Disposition.ACCEPTED, row.version() + 1, null);
    }

    /**
     * Why this delivery no longer applies, or {@code null} if it does.
     *
     * <p>An older revision and a newer one are different mistakes: older means the run is behind the case and
     * will never catch up (STALE, no retry), newer means the run invented a revision that does not exist
     * (a protocol error, refused). Reporting the second as stale would tell a broken producer to stop
     * retrying something that was never valid.
     */
    private static String staleReason(CaseRow row, AgentCallback callback) {
        if (callback.inputRevision() > row.inputRevision()) {
            throw new CaseService.SemanticInvalidException("input_revision " + callback.inputRevision()
                    + " is ahead of this case, which is at revision " + row.inputRevision());
        }
        if (callback.inputRevision() < row.inputRevision()) {
            return "the case has moved to revision " + row.inputRevision() + ", so this run's revision "
                    + callback.inputRevision() + " is no longer current";
        }
        if (row.status().isTerminal()) {
            return "this case already ended as " + row.status();
        }
        if (RUN_HANDED_OVER.contains(row.status())) {
            return "this case is " + row.status() + ", so a human has taken it over";
        }
        return null;
    }

    /**
     * STARTED moves the case to ANALYZING, except when it arrives late.
     *
     * <p>"A late STARTED never rolls the case state back" (docs/core-contracts.md:59) means the status is only
     * moved forward: from QUEUED, or from WAITING_CUSTOMER when this revision has not asked a question — which
     * is a resumed run, because the customer answering moved the revision. A STARTED at the revision the
     * question was asked at leaves the case waiting for the customer, because that is still true.
     */
    private CaseStatus startedStatus(CaseRow row, AgentCallback callback) {
        if (row.status() == CaseStatus.QUEUED) {
            return CaseStatus.ANALYZING;
        }
        if (row.status() == CaseStatus.WAITING_CUSTOMER && !alreadyAsked(row.caseId(), callback.inputRevision())) {
            return CaseStatus.ANALYZING;
        }
        return row.status();
    }

    /**
     * QUESTION is the run's terminal act for this revision, so it may only happen once per revision.
     *
     * <p>The contract makes QUESTION and PROPOSAL mutually exclusive terminal kinds: asking is how the run
     * ends, and it resumes on a new revision once the customer answers. A second question set at the same
     * revision would mean the run did not end when it said it did — and the revision is exactly what tells the
     * two situations apart.
     */
    private CaseStatus questionStatus(CaseRow row, AgentCallback callback, AgentCallback.Questions questions) {
        requireNotAlreadyAsked(row, callback);
        return CaseStatus.WAITING_CUSTOMER;
    }

    /**
     * FAILED either queues the case again or hands it to a human, and the difference is {@code retryable}.
     *
     * <p>That is the core flow's handoff: a failure that trying again cannot fix is not a reason to loop, it is
     * a reason for a person to look (docs/core-scope.md:7). A failure at a revision that already asked a
     * question is refused for the same reason a second question is.
     */
    private CaseStatus failureStatus(CaseRow row, AgentCallback callback, AgentCallback.Failure failure) {
        requireNotAlreadyAsked(row, callback);
        return failure.retryable() ? CaseStatus.QUEUED : CaseStatus.PENDING_REVIEW;
    }

    /**
     * The one refusal that is about this deployment rather than about the delivery.
     *
     * <p>It is a 422 and not a 501 because the contract declares no such status for this route, and it is not a
     * silent acceptance because a proposal nobody checked is exactly what Java owns the amount to prevent.
     * The message says what is missing, so the caller learns something it can act on.
     */
    private static CaseService.SemanticInvalidException proposalsAreNotAcceptedYet() {
        return new CaseService.SemanticInvalidException(
                "a proposal cannot be accepted until its citations and amounts can be re-checked against"
                        + " this service's own records, which this deployment does not do yet");
    }

    private void requireNotAlreadyAsked(CaseRow row, AgentCallback callback) {
        if (alreadyAsked(row.caseId(), callback.inputRevision())) {
            throw new CaseService.SemanticInvalidException("revision " + callback.inputRevision()
                    + " already asked the customer for information, which ended the run for that revision");
        }
    }

    /** Whether this revision already has a question row. The trajectory is the record, so it is the check. */
    private boolean alreadyAsked(String caseId, int revision) {
        return !cases.findDetailsAtRevision(caseId, TimelineEventType.QUESTION_REQUIRED.name(), revision)
                .isEmpty();
    }

    private void claim(
            String caseId,
            AgentCallback callback,
            String payloadHash,
            AgentCallback.Disposition disposition,
            Instant now) {
        inbox.insert(
                callback.callbackId(),
                caseId,
                callback.runId(),
                callback.inputRevision(),
                callback.kind().name(),
                disposition.name(),
                payloadHash,
                callback.traceparent(),
                now);
    }

    /** The payload read once, as the record its kind requires and checked against the contract's limits. */
    private Payload parse(AgentCallback callback) {
        return switch (callback.kind()) {
            case STARTED ->
                new Payload(
                        AgentCallbackValidation.started(callback.payload(mapper, AgentCallback.Started.class)),
                        null,
                        null);
            case QUESTION ->
                new Payload(
                        null,
                        AgentCallbackValidation.questions(callback.payload(mapper, AgentCallback.Questions.class)),
                        null);
            case FAILED ->
                new Payload(
                        null,
                        null,
                        AgentCallbackValidation.failure(callback.payload(mapper, AgentCallback.Failure.class)));
            case PROPOSAL -> throw proposalsAreNotAcceptedYet();
        };
    }

    private static TimelineEventType eventType(AgentCallback.Kind kind) {
        return switch (kind) {
            case STARTED -> TimelineEventType.AGENT_STARTED;
            case QUESTION -> TimelineEventType.QUESTION_REQUIRED;
            case PROPOSAL -> TimelineEventType.PROPOSAL_READY;
            case FAILED -> TimelineEventType.AGENT_FAILED;
        };
    }

    /**
     * What the trajectory row keeps.
     *
     * <p>The row keeps facts and {@link TimelineSummary} turns them into the sentence a person reads; the two
     * are never stored separately, so they cannot disagree. Only what a reader of this event needs is here —
     * not the whole payload, whose own facts belong in the table that owns them.
     */
    private String detail(AgentCallback callback, Payload payload) {
        ObjectNode detail = mapper.createObjectNode();
        detail.put("run_id", callback.runId());
        detail.put("kind", callback.kind().name());
        switch (callback.kind()) {
            case STARTED -> {
                if (payload.started().startedAt() != null) {
                    detail.put("started_at", payload.started().startedAt().toString());
                }
            }
            case QUESTION -> {
                detail.put("question_id", payload.questions().questionId());
                ArrayNode fields = detail.putArray("fields");
                payload.questions().questions().forEach(question -> fields.add(question.field()));
                if (payload.questions().reasonCodes() != null) {
                    ArrayNode codes = detail.putArray("reason_codes");
                    payload.questions().reasonCodes().forEach(codes::add);
                }
            }
            case FAILED -> {
                detail.put("retryable", payload.failure().retryable());
                ArrayNode codes = detail.putArray("reason_codes");
                payload.failure().reasonCodes().forEach(codes::add);
            }
            case PROPOSAL -> throw proposalsAreNotAcceptedYet();
        }
        return CanonicalJson.canonicalize(detail);
    }

    private int nextSequence(String caseId) {
        Integer highest = cases.highestSequence(caseId);
        return highest == null ? 1 : highest + 1;
    }

    /** Exactly one of the three is present, decided by the kind. */
    private record Payload(
            AgentCallback.Started started, AgentCallback.Questions questions, AgentCallback.Failure failure) {}
}
