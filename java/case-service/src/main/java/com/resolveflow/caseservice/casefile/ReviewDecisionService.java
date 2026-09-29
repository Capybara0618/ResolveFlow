package com.resolveflow.caseservice.casefile;

import com.resolveflow.caseservice.order.CommerceOrderLineClient;
import com.resolveflow.shared.contract.CanonicalJson;
import com.resolveflow.shared.security.AuthenticatedPrincipal;
import java.time.Clock;
import java.time.Instant;
import java.util.UUID;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import tools.jackson.databind.ObjectMapper;
import tools.jackson.databind.node.ObjectNode;

/**
 * The human decision on an authorisation (C03.3b, docs/core-contracts.md:34).
 *
 * <p>Two locks guard it and they guard different things. {@code If-Match} carries the case version the
 * reviewer read, so a decision cannot be applied to a state nobody looked at; the body carries the
 * authorisation version, so nobody can decide a version that has already moved. The second lock is also what
 * makes a decision final: the version and the waiting status are both part of the UPDATE, so two reviewers
 * deciding at once cannot both win (docs/domain-model.md:31).
 *
 * <p>Approval re-validates before it approves, because hours may have passed since the payload was fixed:
 * the revision it fixed has to still be the case's revision, the payload hash has to still be the one this
 * service recomputes from its own rows, and Commerce has to still be able to pay the line. The three answers
 * are deliberately not the same answer — see {@link #revalidationFailure}.
 *
 * <p>Only staff decide: a CUSTOMER token is refused, because the person who asked for the money cannot also
 * authorise it. The role is recorded, so the difference between a reviewer and an operator is visible in the
 * record rather than assumed.
 */
@Service
public class ReviewDecisionService {

    /**
     * A refusal that also lapsed the authorisation, and therefore must not be rolled back.
     *
     * <p>Spring rolls a transaction back on a runtime exception, which is the right default and the wrong
     * answer here: the authorisation was lapsed because it can never be applied, and rolling that back would
     * leave a row a reviewer would keep retrying. So this class exists to be named in {@code noRollbackFor} —
     * the refusal is the answer, the lapse is the effect, and both are true.
     */
    public static class AuthorizationLapsedException extends CaseStateConflictException {

        private static final long serialVersionUID = 1L;

        public AuthorizationLapsedException(String message) {
            super(message);
        }
    }

    private final CaseRepository cases;
    private final AuthorizationRepository authorizations;
    private final ReviewQuestionService questions;
    private final CommerceOrderLineClient commerce;
    private final Clock clock;
    private final ObjectMapper mapper;

    public ReviewDecisionService(
            CaseRepository cases,
            AuthorizationRepository authorizations,
            ReviewQuestionService questions,
            CommerceOrderLineClient commerce,
            Clock clock,
            ObjectMapper mapper) {
        this.cases = cases;
        this.authorizations = authorizations;
        this.questions = questions;
        this.commerce = commerce;
        this.clock = clock;
        this.mapper = mapper;
    }

    @Transactional(noRollbackFor = AuthorizationLapsedException.class)
    public ReviewResponse decide(
            AuthenticatedPrincipal principal, String caseId, String ifMatch, ReviewRequest request) {
        String authorizationId = requireUuid(request.authorizationId());
        long expectedVersion = requireVersion(request.authorizationVersion(), "authorization_version");
        ReviewDecision decision = ReviewDecision.of(request.decision());
        String reason = requireReason(request.reason());
        long seenCaseVersion = requireIfMatch(ifMatch);
        requireStaff(principal);

        CaseRow row = cases.findCaseForUpdate(caseId);
        if (row == null || !row.visibleTo(principal)) {
            throw new CaseReadService.CaseNotVisibleException();
        }
        if (row.status().isTerminal()) {
            throw new CaseStateConflictException(
                    "this case already ended as " + row.status() + "; there is nothing left to decide");
        }

        AuthorizationRepository.StoredAuthorization stored = authorizations.findByAuthorizationId(authorizationId);
        if (stored == null || !stored.caseId().equals(caseId)) {
            throw new CaseService.SemanticInvalidException(
                    "authorization_id " + authorizationId + " is not an authorisation of this case");
        }
        requireCurrentReading(row, seenCaseVersion);
        requireCurrentVersion(stored, expectedVersion);
        requireWaiting(stored);

        Instant now = Instant.now(clock);
        AuthorizationStatus outcome =
                switch (decision) {
                    case APPROVE -> approve(row, stored, principal, reason, now);
                    case REJECT -> decideAndClose(row, stored, principal, reason, now);
                    case REQUEST_INFO -> lapseAndAsk(row, stored, principal, reason, now);
                };
        CaseRow after = cases.findCase(caseId);
        return new ReviewResponse(caseId, authorizationId, stored.authorizationVersion() + 1, outcome, after.version());
    }

    /**
     * Approve, after checking that the payload this authorisation fixed is still the payment to make.
     *
     * <p>The hash is recomputed from this service's own rows (the authorisation plus the case) rather than
     * compared with a stored copy of itself: if the two disagree, a row changed underneath the decision, and
     * approving would execute an amount nobody approved.
     */
    private AuthorizationStatus approve(
            CaseRow row,
            AuthorizationRepository.StoredAuthorization stored,
            AuthenticatedPrincipal principal,
            String reason,
            Instant now) {
        String failure = revalidationFailure(row, stored);
        if (failure != null) {
            lapse(stored, failure, now);
            throw new AuthorizationLapsedException(failure);
        }
        record(stored, AuthorizationStatus.APPROVED, principal, reason, now);
        if (cases.transition(row.caseId(), row.status().name(), CaseStatus.AUTHORIZED.name(), now) != 1) {
            throw new CaseStateConflictException(
                    "this case is no longer in " + row.status() + "; nothing was approved");
        }
        cases.insertTimeline(
                row.caseId(),
                UUID.randomUUID().toString(),
                cases.nextTimelineSequence(row.caseId()),
                TimelineEventType.AUTHORIZATION_DECIDED.name(),
                decisionDetail(row, stored, ReviewDecision.APPROVE, principal, reason),
                now,
                row.inputRevision());
        return AuthorizationStatus.APPROVED;
    }

    /**
     * Reject: the authorisation is refused and the case ends, in one transaction.
     *
     * <p>A refusal is a decision about this input revision, and the case it belongs to has no other live
     * authorisation, so the honest end is the terminal one: a case left in PENDING_REVIEW after its only
     * proposal was refused would sit in the review queue forever with nothing to review. The line's active
     * slot is released here for the same reason cancellation releases it — a terminal case does not occupy a
     * line (docs/domain-model.md:26).
     */
    private AuthorizationStatus decideAndClose(
            CaseRow row,
            AuthorizationRepository.StoredAuthorization stored,
            AuthenticatedPrincipal principal,
            String reason,
            Instant now) {
        record(stored, AuthorizationStatus.REJECTED, principal, reason, now);
        if (cases.transition(row.caseId(), row.status().name(), CaseStatus.CLOSED_REJECTED.name(), now) != 1) {
            throw new CaseStateConflictException(
                    "this case is no longer in " + row.status() + "; nothing was rejected");
        }
        cases.releaseActiveSlot(row.merchantId(), row.lineId());
        cases.insertTimeline(
                row.caseId(),
                UUID.randomUUID().toString(),
                cases.nextTimelineSequence(row.caseId()),
                TimelineEventType.AUTHORIZATION_DECIDED.name(),
                decisionDetail(row, stored, ReviewDecision.REJECT, principal, reason),
                now,
                row.inputRevision());
        ObjectNode closing = mapper.createObjectNode();
        closing.put("status", CaseStatus.CLOSED_REJECTED.name());
        cases.insertTimeline(
                row.caseId(),
                UUID.randomUUID().toString(),
                cases.nextTimelineSequence(row.caseId()),
                TimelineEventType.CASE_CLOSED.name(),
                CanonicalJson.canonicalize(closing),
                now,
                row.inputRevision());
        return AuthorizationStatus.REJECTED;
    }

    /**
     * Ask the customer for more material: the case goes back to waiting, and this authorisation lapses.
     *
     * <p>EXPIRED rather than REVOKED because nobody withdrew it on its merits, and rather than REJECTED
     * because the reviewer did not say no — they asked a question. It can never be applied afterwards: the
     * material the customer is about to supply moves the revision, and the payload was fixed for the old one.
     * The reviewer's reason is kept, because "who asked for what" is a fact the next reader needs.
     */
    private AuthorizationStatus lapseAndAsk(
            CaseRow row,
            AuthorizationRepository.StoredAuthorization stored,
            AuthenticatedPrincipal principal,
            String reason,
            Instant now) {
        questions.requireAllowed(row);
        record(stored, AuthorizationStatus.EXPIRED, principal, reason, now);
        if (cases.transition(row.caseId(), row.status().name(), CaseStatus.WAITING_CUSTOMER.name(), now) != 1) {
            throw new CaseStateConflictException("this case is no longer in " + row.status() + "; nothing was asked");
        }
        cases.insertTimeline(
                row.caseId(),
                UUID.randomUUID().toString(),
                cases.nextTimelineSequence(row.caseId()),
                TimelineEventType.AUTHORIZATION_DECIDED.name(),
                decisionDetail(row, stored, ReviewDecision.REQUEST_INFO, principal, reason),
                now,
                row.inputRevision());
        questions.record(row, row.inputRevision(), principal, reason, "HUMAN_AUTHORIZATION", now);
        return AuthorizationStatus.EXPIRED;
    }

    /**
     * Why this authorisation can no longer be approved, or {@code null} if it can.
     *
     * <p>Three checks, in the order the facts can be checked against each other. The revision and the hash are
     * statements about what <em>this service</em> fixed, so a failure is permanent: the payload can never
     * become applicable again, and the caller gets a message that says which fact moved. Commerce's answer is
     * about the world, so a failure there is reported without lapsing anything — a line whose order ledger has
     * reserved the money today may pay tomorrow, and turning that into a dead authorisation would be this
     * service inventing a decision.
     */
    private String revalidationFailure(CaseRow row, AuthorizationRepository.StoredAuthorization stored) {
        if (stored.inputRevision() != row.inputRevision()) {
            return "this authorisation fixed its payload for input revision " + stored.inputRevision()
                    + " but the case is at revision " + row.inputRevision()
                    + "; the input it was checked against has changed, so it can never be applied";
        }
        // Rebuilt rather than remembered: the hash below is only evidence about this authorisation while the
        // same assembly produces the command that is eventually sent (RefundCommand.fixedBy, C05.2a).
        RefundCommand command = RefundCommand.fixedBy(stored, row);
        if (!command.payloadHash(mapper).equals(stored.payloadHash())) {
            return "the payload hash of this authorisation cannot be recomputed from its own row, so what it"
                    + " would execute is not what was approved";
        }
        var context = commerce.readLineContext(row.lineId());
        if (context.isEmpty()) {
            throw new CaseStateConflictException("Commerce no longer has line " + row.lineId()
                    + ", so the payment this authorisation fixed cannot be made from the record it names");
        }
        var line = context.get();
        if (!row.merchantId().equals(line.merchantId()) || !row.customerId().equals(line.customerId())) {
            throw new CaseStateConflictException("line " + row.lineId()
                    + " is no longer this case's line, so the authorisation does not describe a payment to it");
        }
        if (line.refundableAmountMinor() < stored.amountMinor()) {
            throw new CaseStateConflictException("line " + row.lineId() + " can currently refund "
                    + line.refundableAmountMinor() + " minor units but this authorisation is for "
                    + stored.amountMinor() + "; nothing was approved");
        }
        return null;
    }

    /** Write the decision, under both locks, and insist that exactly one row changed. */
    private void record(
            AuthorizationRepository.StoredAuthorization stored,
            AuthorizationStatus outcome,
            AuthenticatedPrincipal principal,
            String reason,
            Instant now) {
        if (authorizations.decide(
                        stored.authorizationId(),
                        stored.authorizationVersion(),
                        outcome.name(),
                        principal.subject(),
                        principal.role().name(),
                        reason,
                        now)
                != 1) {
            throw new CaseStateConflictException("authorisation " + stored.authorizationId()
                    + " was decided by somebody else, or is no longer at version "
                    + stored.authorizationVersion() + "; nothing was recorded");
        }
    }

    /**
     * Lapse an authorisation nobody decided, and insist that it happened.
     *
     * <p>The guards above make a zero-row update unreachable (the version is current and the status is
     * waiting), which is exactly why it must not be ignored: if it ever did happen, something changed
     * underneath this transaction, and telling the caller "it can never be applied" would be a claim this
     * service could not stand behind. A zero here is therefore a plain conflict, which rolls the attempt back.
     */
    private void lapse(AuthorizationRepository.StoredAuthorization stored, String reason, Instant now) {
        if (authorizations.lapse(stored.authorizationId(), stored.authorizationVersion(), reason, now) != 1) {
            throw new CaseStateConflictException("authorisation " + stored.authorizationId()
                    + " changed while it was being re-checked; nothing was decided");
        }
    }

    private void requireStaff(AuthenticatedPrincipal principal) {
        CaseStaff.require(
                principal,
                "a CUSTOMER may not decide an authorisation; the case's customer is the party the"
                        + " decision is about");
    }

    private static void requireCurrentReading(CaseRow row, long seenCaseVersion) {
        if (seenCaseVersion != row.version()) {
            throw new CaseStateConflictException("If-Match is \"" + seenCaseVersion + "\" but this case is at"
                    + " version " + row.version() + "; the reading this decision was made from is out of date");
        }
    }

    private static void requireCurrentVersion(
            AuthorizationRepository.StoredAuthorization stored, long expectedVersion) {
        if (expectedVersion != stored.authorizationVersion()) {
            throw new CaseStateConflictException("authorization_version " + expectedVersion
                    + " is not the current version " + stored.authorizationVersion()
                    + "; the decision was made from a version that has moved");
        }
    }

    private static void requireWaiting(AuthorizationRepository.StoredAuthorization stored) {
        if (stored.authorizationStatus() != AuthorizationStatus.PENDING_REVIEW) {
            String decided = stored.decidedBy() == null
                    ? ""
                    : " (decided by " + stored.decidedBy() + " at " + stored.decidedAt() + ")";
            throw new CaseStateConflictException(
                    "this authorisation is already " + stored.status() + decided + "; a decision is final");
        }
    }

    private static String requireReason(String reason) {
        if (reason == null || reason.isBlank()) {
            throw new CaseService.SemanticInvalidException(
                    "reason is required; a decision nobody explained" + " is a decision the next reader cannot act on");
        }
        if (reason.length() > 1000) {
            throw new CaseService.SemanticInvalidException("reason must be at most 1000 characters");
        }
        return reason;
    }

    private static String requireUuid(String value) {
        if (value == null
                || !value.matches("^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")) {
            throw new CaseService.SemanticInvalidException("authorization_id must be a UUID, got " + value);
        }
        return value;
    }

    private static long requireVersion(Long value, String member) {
        if (value == null || value < 1 || value > 9007199254740991L) {
            throw new CaseService.SemanticInvalidException(member + " must be a positive version, got " + value);
        }
        return value;
    }

    /** {@code If-Match} is required and quoted, because an unquoted version is not an ETag (contract). */
    private static long requireIfMatch(String ifMatch) {
        if (ifMatch == null || !ifMatch.matches("^\"[1-9][0-9]{0,15}\"$")) {
            throw new CaseService.SemanticInvalidException(
                    "If-Match must be the quoted case version, got " + (ifMatch == null ? "nothing" : ifMatch));
        }
        return Long.parseLong(ifMatch.substring(1, ifMatch.length() - 1));
    }

    private String decisionDetail(
            CaseRow row,
            AuthorizationRepository.StoredAuthorization stored,
            ReviewDecision decision,
            AuthenticatedPrincipal principal,
            String reason) {
        ObjectNode detail = mapper.createObjectNode();
        detail.put("decision", decision.name());
        detail.put("authorization_id", stored.authorizationId());
        // The version the decision produced: the authorisation moved to version+1 with this act.
        detail.put("authorization_version", stored.authorizationVersion() + 1);
        detail.put("reason", reason);
        detail.put("decided_by", principal.subject());
        detail.put("decided_role", principal.role().name());
        detail.put("case_status", caseStatusAfter(decision).name());
        detail.put("input_revision", row.inputRevision());
        return CanonicalJson.canonicalize(detail);
    }

    private static CaseStatus caseStatusAfter(ReviewDecision decision) {
        return switch (decision) {
            case APPROVE -> CaseStatus.AUTHORIZED;
            case REJECT -> CaseStatus.CLOSED_REJECTED;
            case REQUEST_INFO -> CaseStatus.WAITING_CUSTOMER;
        };
    }
}
