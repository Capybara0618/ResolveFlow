package com.resolveflow.caseservice.casefile;

import com.resolveflow.shared.contract.CanonicalJson;
import com.resolveflow.shared.security.AuthenticatedPrincipal;
import com.resolveflow.shared.security.Role;
import java.time.Clock;
import java.time.Instant;
import java.util.List;
import java.util.UUID;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import tools.jackson.databind.ObjectMapper;
import tools.jackson.databind.node.ObjectNode;

/**
 * Appending customer material (docs/core-contracts.md:30).
 *
 * <p>Three rules meet here, and each is enforced where it cannot be bypassed:
 *
 * <ol>
 *   <li><b>Provenance.</b> A customer may submit a statement; merchant staff may record their own
 *       verification; nobody may submit a carrier or ledger fact as their own. That is not a policy
 *       choice about who is trustworthy — it is the difference between material and a claim about the
 *       world that the platform is supposed to check itself (docs/agent-spec.md).
 *   <li><b>The revision is the server's.</b> The request has no revision member, so material lands on
 *       the revision the case is at, plus one. There is no spelling of the request that writes into a
 *       past revision, which is a stronger guarantee than validating a number the client sent.
 *   <li><b>Once the input is consumed it is closed.</b> After consumption the operation is running and
 *       the input it was authorised against cannot change; that answer is 409, not a silent bump
 *       (docs/core-contracts.md:30).
 *   <li><b>New input retires the live authorisation.</b> An authorisation is fixed to the revision its
 *       payload was hashed from, so a revision that moves leaves an approval describing input the case no
 *       longer has. Both append routes therefore revoke it in the same transaction that writes the
 *       material and name it in the response (C03.3c, {@link LiveAuthorization}).
 * </ol>
 *
 * <p>The authorization check remains in force when a failed refund returns the case to review.
 */
@Service
public class CaseEvidenceService {

    private static final int MAX_TEXT = 8000;

    /** The contract's {@code maxItems} on the case view's evidence: material must not fall out of the view. */
    public static final int MAX_RECORDS = 64;

    private static final int MAX_REASON = 1000;

    private final CaseRepository cases;
    private final EvidenceRepository evidence;
    private final AgentRunBindingRepository bindings;
    private final LiveAuthorization liveAuthorisations;
    private final Clock clock;
    private final CaseCollaborationService collaboration;
    private final ObjectMapper mapper = new ObjectMapper();

    public CaseEvidenceService(
            CaseRepository cases,
            EvidenceRepository evidence,
            AgentRunBindingRepository bindings,
            LiveAuthorization liveAuthorisations,
            Clock clock,
            CaseCollaborationService collaboration) {
        this.cases = cases;
        this.evidence = evidence;
        this.bindings = bindings;
        this.liveAuthorisations = liveAuthorisations;
        this.clock = clock;
        this.collaboration = collaboration;
    }

    // One transaction for the whole append: the row lock, the material, the revision bump and the
    // trajectory entry. Nothing here calls another service, so unlike case creation there is no
    // network call to keep outside it (docs/engineering.md:68).
    @Transactional
    public EvidenceSubmissionResponse append(
            AuthenticatedPrincipal principal, String caseId, EvidenceAppendRequest request) {
        return append(principal, caseId, request, null);
    }

    @Transactional
    public EvidenceSubmissionResponse append(
            AuthenticatedPrincipal principal,
            String caseId,
            EvidenceAppendRequest request,
            CaseCollaborationService.WritePermit permit) {
        EvidenceSourceType kind = parseKind(request);
        String text = requireText(request);
        String questionId = normaliseQuestionId(request);

        // The case row is locked for the whole append, so the revision the material records is the
        // revision the case is at when the row is written (docs/domain-model.md:36: 锁case行并校验).
        CaseRow row = lockedVisibleCase(principal, caseId);
        if (principal.role().isMerchantStaff()) collaboration.requireOwner(principal, row, permit);
        requireOpenInput(row);
        requireProvenance(principal, kind);
        requireRoom(caseId);
        requireQuestionAssociation(row, questionId);

        Instant now = Instant.now(clock);
        int revision = row.inputRevision() + 1;
        String evidenceId = UUID.randomUUID().toString();
        Written written = write(
                row,
                principal,
                evidenceId,
                kind,
                sourceRef(principal, kind),
                String.valueOf(revision),
                contentHash(caseId, kind, text, principal, questionId),
                revision,
                now,
                text,
                questionId,
                null,
                null,
                appendedDetail(kind, text, questionId, principal),
                retireBecause("new customer material", revision));
        return new EvidenceSubmissionResponse(
                row.caseId(), written.inputRevision(), written.version(), written.revokedAuthorizationId());
    }

    /**
     * A reviewer's verification of one record (docs/core-contracts.md:35).
     *
     * <p>What this route adds over the generic append is structure, and the structure is the point: the new
     * record names the record it verified and states what the reviewer concluded, so a later reader (and a
     * later re-check) can act on it. "The customer statement was not edited" is not a promise made here but a
     * property of the store: neither record is ever updated, so the verified one keeps its text and its hash
     * and both stay readable side by side.
     *
     * <p>New input retires the case's live authorisation, and it does so whatever the reviewer concluded:
     * what invalidated the fixed payload is the revision moving, not the verdict. Revoking only on REFUTED
     * would leave a CONFIRMED verification — which is also new input — with an approval that describes the
     * revision before it.
     */
    @Transactional
    public ReviewedEvidenceResponse review(
            AuthenticatedPrincipal principal, String caseId, ReviewedEvidenceRequest request) {
        return review(principal, caseId, request, null);
    }

    @Transactional
    public ReviewedEvidenceResponse review(
            AuthenticatedPrincipal principal,
            String caseId,
            ReviewedEvidenceRequest request,
            CaseCollaborationService.WritePermit permit) {
        EvidenceSourceType kind = EvidenceSourceType.REVIEWER_VERIFICATION;
        requireProvenance(principal, kind);
        String sourceEvidenceId = requireUuid(request.sourceEvidenceId(), "source_evidence_id");
        VerificationResult result = parseResult(request);
        String reason = requireReason(request);

        CaseRow row = lockedVisibleCase(principal, caseId);
        collaboration.requireOwner(principal, row, permit);
        requireOpenInput(row);
        requireRoom(caseId);

        EvidenceRepository.EvidenceRow verified = evidence.findEvidence(caseId, sourceEvidenceId);
        if (verified == null) {
            throw new CaseService.SemanticInvalidException(
                    "source_evidence_id " + sourceEvidenceId + " is not a record of this case");
        }
        // Verifying a verification would make "what was verified" regress into a chain, and the chain's
        // last link would be the only statement with any material behind it. Material is verified once.
        if (verified.kind() == EvidenceSourceType.REVIEWER_VERIFICATION) {
            throw new CaseService.SemanticInvalidException(
                    "source_evidence_id " + sourceEvidenceId + " is itself a verification; material is verified,"
                            + " not the record of somebody's verification of it");
        }

        Instant now = Instant.now(clock);
        int revision = row.inputRevision() + 1;
        String evidenceId = UUID.randomUUID().toString();
        Written written = write(
                row,
                principal,
                evidenceId,
                kind,
                "evidence:" + sourceEvidenceId,
                String.valueOf(verified.inputRevision()),
                verificationContentHash(caseId, sourceEvidenceId, verified.contentHash(), result, reason, principal),
                revision,
                now,
                reason,
                null,
                sourceEvidenceId,
                result,
                verificationDetail(result, sourceEvidenceId, reason, principal),
                retireBecause("a reviewer's verification " + result.name(), revision));
        return ReviewedEvidenceResponse.recorded(
                row.caseId(),
                written.evidenceId(),
                written.inputRevision(),
                written.version(),
                written.revokedAuthorizationId());
    }

    /**
     * The retirement sentence a reader of the old authorisation row will find.
     *
     * <p>It names the act and the revision it moved to, because "why is this approval withdrawn" is the next
     * reader's question, and "something changed" is not an answer. The revision it moved <em>from</em> is not
     * in the sentence: the authorisation's own {@code input_revision} column already says that, and two places
     * to read one number is how they start disagreeing.
     */
    private static String retireBecause(String because, int revision) {
        return because + " moved the input to revision " + revision;
    }

    /**
     * What one append produced: the new record's id, the revision it landed on, the case's new version and
     * the authorisation it retired ({@code null} when the case had none alive).
     */
    private record Written(String evidenceId, int inputRevision, long version, String revokedAuthorizationId) {}

    /**
     * The one place an append happens: the record, the revision bump, the retirement of the approval fixed to
     * the old revision, and the trajectory row.
     *
     * <p>Both routes go through it so that "appending material always moves the revision, always retires a
     * live approval and always leaves a trajectory row" cannot hold for one route and not the other.
     *
     * <p>The retirement happens here rather than in the caller's argument list because order is the point: the
     * material is already recorded when the approval is withdrawn, so a reader can never find the new revision
     * on the case while the old approval is still live. Both writes are in the caller's transaction, so either
     * both are visible or neither is.
     */
    private Written write(
            CaseRow row,
            AuthenticatedPrincipal principal,
            String evidenceId,
            EvidenceSourceType kind,
            String sourceRef,
            String sourceVersion,
            String contentHash,
            int revision,
            Instant now,
            String content,
            String questionId,
            String reviewedEvidenceId,
            VerificationResult result,
            String detail,
            String retirementReason) {
        evidence.insertEvidence(
                row.caseId(),
                evidenceId,
                kind.name(),
                sourceRef,
                sourceVersion,
                contentHash,
                revision,
                now,
                content,
                questionId,
                reviewedEvidenceId,
                result == null ? null : result.name(),
                principal.subject(),
                principal.role().name(),
                now);
        evidence.bumpRevision(row.caseId(), now);
        bindings.insert(row.caseId(), revision, AgentRunId.forRevision(row.caseId(), revision), now);
        String revoked = liveAuthorisations.revoke(row.caseId(), retirementReason, now);
        cases.insertTimeline(
                row.caseId(),
                UUID.randomUUID().toString(),
                cases.nextTimelineSequence(row.caseId()),
                TimelineEventType.EVIDENCE_APPENDED.name(),
                detail,
                now,
                revision);
        return new Written(evidenceId, revision, row.version() + 1, revoked);
    }

    /** A response to a recorded question must name that question so the round remains traceable. */
    private void requireQuestionAssociation(CaseRow row, String questionId) {
        if (row.status() != CaseStatus.WAITING_CUSTOMER) return;
        String expected = null;
        List<TimelineEventRow> timeline = cases.findTimeline(row.caseId());
        for (int index = timeline.size() - 1; index >= 0; index--) {
            TimelineEventRow event = timeline.get(index);
            if (event.kind() == TimelineEventType.QUESTION_REQUIRED) {
                if (!Instant.now(clock).isBefore(ReviewQuestionService.answerDeadline(row, event))) {
                    throw new CaseStateConflictException(
                            "the question's answer deadline has passed; merchant review is required");
                }
                expected = JsonField.of(event.detail(), "question_id");
                break;
            }
        }
        // Legacy/test rows may have been put into WAITING_CUSTOMER without a question event. There is no
        // identifier to require in that case; real question flows always record one.
        if (expected == null) return;
        if (!expected.equals(questionId)) {
            throw new CaseService.SemanticInvalidException(
                    "question_id must name the question currently awaiting an answer: " + expected);
        }
    }

    private CaseRow lockedVisibleCase(AuthenticatedPrincipal principal, String caseId) {
        CaseRow row = cases.findCaseForUpdate(caseId);
        if (row == null || !row.visibleTo(principal)) {
            throw new CaseReadService.CaseNotVisibleException();
        }
        return row;
    }

    /**
     * The case view's evidence array is capped at 64 by the contract, so a case that reached the cap must
     * refuse new material rather than let the oldest record silently fall out of the view.
     *
     * <p>Refusing is the honest half of a bounded view: a reader that cannot see a record must be told the
     * record was not accepted, not left to assume it was never submitted.
     */
    private void requireRoom(String caseId) {
        int held = evidence.countForCase(caseId);
        if (held >= MAX_RECORDS) {
            throw new CaseService.SemanticInvalidException("this case already holds " + MAX_RECORDS
                    + " evidence records, which is the case view's declared bound; no further material is"
                    + " accepted because it would not be readable");
        }
    }

    private void requireOpenInput(CaseRow row) {
        liveAuthorisations.requireUnconsumed(row.caseId());
        // A terminal case and a consumed case both refuse material, and they are not the same thing: one
        // has ended, the other is running. Saying "already executing" about a cancelled case would be a
        // false statement about the case in the one message a client will read.
        if (row.status().isTerminal()) {
            throw new CaseStateConflictException(
                    "this case already ended as " + row.status() + "; the input of an ended case cannot change");
        }
        if (row.status() == CaseStatus.EXECUTING || row.status() == CaseStatus.RECONCILING) {
            throw new CaseStateConflictException(
                    "this case is already executing; the input of a consumed case cannot change");
        }
    }

    private void requireProvenance(AuthenticatedPrincipal principal, EvidenceSourceType kind) {
        if (kind.isMachineRead()) {
            throw new CaseService.ForbiddenScopeException(
                    kind + " is read by the investigation, not asserted by a caller");
        }
        boolean customerSubmittingAStatement =
                principal.role() == Role.CUSTOMER && kind == EvidenceSourceType.CUSTOMER_STATEMENT;
        boolean staffRecordingAVerification =
                CaseStaff.canReview(principal) && kind == EvidenceSourceType.REVIEWER_VERIFICATION;
        if (!customerSubmittingAStatement && !staffRecordingAVerification) {
            throw new CaseService.ForbiddenScopeException(
                    "a " + principal.role() + " may not submit " + kind + " as its own material");
        }
    }

    private EvidenceSourceType parseKind(EvidenceAppendRequest request) {
        if (request.evidenceKind() == null || request.evidenceKind().isBlank()) {
            throw new CaseService.SemanticInvalidException("evidence_kind is required");
        }
        try {
            return EvidenceSourceType.of(request.evidenceKind());
        } catch (IllegalArgumentException error) {
            throw new CaseService.SemanticInvalidException(error.getMessage());
        }
    }

    private static String requireText(EvidenceAppendRequest request) {
        if (request.text() == null || request.text().isBlank()) {
            throw new CaseService.SemanticInvalidException("text is required");
        }
        if (request.text().length() > MAX_TEXT) {
            throw new CaseService.SemanticInvalidException("text must be at most " + MAX_TEXT + " characters");
        }
        return request.text();
    }

    private static VerificationResult parseResult(ReviewedEvidenceRequest request) {
        try {
            return VerificationResult.of(request.verificationResult());
        } catch (IllegalArgumentException error) {
            throw new CaseService.SemanticInvalidException(error.getMessage());
        }
    }

    private static String requireReason(ReviewedEvidenceRequest request) {
        if (request.reason() == null || request.reason().isBlank()) {
            throw new CaseService.SemanticInvalidException("reason is required");
        }
        if (request.reason().length() > MAX_REASON) {
            throw new CaseService.SemanticInvalidException("reason must be at most " + MAX_REASON + " characters");
        }
        return request.reason();
    }

    /**
     * The named record, checked for shape before the lookup.
     *
     * <p>The identifier is one this service issues, so a value that is not a uuid is a refusal rather than a
     * lookup that would silently find nothing: "you sent a nonsense id" and "there is no such record" are
     * different client mistakes and get different sentences.
     */
    private static String requireUuid(String raw, String member) {
        if (raw == null || raw.isBlank()) {
            throw new CaseService.SemanticInvalidException(member + " is required");
        }
        try {
            UUID.fromString(raw);
        } catch (IllegalArgumentException error) {
            throw new CaseService.SemanticInvalidException(member + " must be a uuid, not " + raw);
        }
        return raw;
    }

    private static String normaliseQuestionId(EvidenceAppendRequest request) {
        String questionId = request.questionId();
        if (questionId == null || questionId.isBlank()) {
            return null;
        }
        if (questionId.length() > 64) {
            throw new CaseService.SemanticInvalidException("question_id must be at most 64 characters");
        }
        return questionId;
    }

    /**
     * Where the material points, in the shape the evidence source implies.
     *
     * <p>A customer's statement points at the customer who made it; a reviewer's verification points at
     * the reviewer. Neither invents a reference to an external system, because neither read one.
     */
    private static String sourceRef(AuthenticatedPrincipal principal, EvidenceSourceType kind) {
        return kind == EvidenceSourceType.CUSTOMER_STATEMENT
                ? "customer:" + principal.customerId()
                : "reviewer:" + principal.subject();
    }

    /**
     * The hash of what was actually submitted.
     *
     * <p>It covers the text and who said it, so the same words from two people are two records with two
     * hashes. This is what makes "the material did not change" checkable later without re-reading it.
     */
    private String contentHash(
            String caseId, EvidenceSourceType kind, String text, AuthenticatedPrincipal principal, String questionId) {
        ObjectNode node = mapper.createObjectNode();
        node.put("case_id", caseId);
        node.put("evidence_kind", kind.name());
        node.put("text", text);
        node.put("question_id", questionId);
        node.put("submitted_by", principal.subject());
        node.put("submitted_role", principal.role().name());
        return CanonicalJson.contentHash(node);
    }

    private String appendedDetail(
            EvidenceSourceType kind, String text, String questionId, AuthenticatedPrincipal principal) {
        ObjectNode detail = mapper.createObjectNode();
        detail.put("evidence_kind", kind.name());
        detail.put("question_id", questionId);
        detail.put("submitted_by", principal.subject());
        detail.put("submitted_role", principal.role().name());
        detail.put("preview", text.length() <= 200 ? text : text.substring(0, 200));
        return CanonicalJson.canonicalize(detail);
    }

    /**
     * The hash of a verification: the conclusion, the reason, who reached it, and the hash of the record it
     * is about.
     *
     * <p>Covering the verified record's hash is what makes "this conclusion was about that material" a fact
     * rather than a claim: material is never edited, so the hash still identifies exactly what the reviewer
     * looked at, and a verification cannot be re-pointed at a different record without changing its own.
     */
    private String verificationContentHash(
            String caseId,
            String sourceEvidenceId,
            String sourceContentHash,
            VerificationResult result,
            String reason,
            AuthenticatedPrincipal principal) {
        ObjectNode node = mapper.createObjectNode();
        node.put("case_id", caseId);
        node.put("evidence_kind", EvidenceSourceType.REVIEWER_VERIFICATION.name());
        node.put("reviewed_evidence_id", sourceEvidenceId);
        node.put("reviewed_content_hash", sourceContentHash);
        node.put("verification_result", result.name());
        node.put("reason", reason);
        node.put("submitted_by", principal.subject());
        node.put("submitted_role", principal.role().name());
        return CanonicalJson.contentHash(node);
    }

    /** The trajectory detail of a verification: both structured members, so the sentence can state them. */
    private String verificationDetail(
            VerificationResult result, String sourceEvidenceId, String reason, AuthenticatedPrincipal principal) {
        ObjectNode detail = mapper.createObjectNode();
        detail.put("evidence_kind", EvidenceSourceType.REVIEWER_VERIFICATION.name());
        detail.put("reviewed_evidence_id", sourceEvidenceId);
        detail.put("verification_result", result.name());
        detail.put("submitted_by", principal.subject());
        detail.put("submitted_role", principal.role().name());
        detail.put("preview", reason.length() <= 200 ? reason : reason.substring(0, 200));
        return CanonicalJson.canonicalize(detail);
    }
}
