package com.resolveflow.caseservice.casefile;

import com.resolveflow.shared.contract.CanonicalJson;
import com.resolveflow.shared.security.AuthenticatedPrincipal;
import com.resolveflow.shared.security.Role;
import java.time.Clock;
import java.time.Instant;
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
 * </ol>
 *
 * <p>The state check is written against the case status, because the authorisation that consumption
 * belongs to arrives in C03. {@code EXECUTING} and {@code RECONCILING} are reachable only after
 * consumption (docs/domain-model.md:55), so the guard is already correct for those states; C03 will add
 * the authorisation-level check (a consumed authorisation on a case that has not moved yet).
 */
@Service
public class CaseEvidenceService {

    private static final int MAX_TEXT = 8000;

    private final CaseRepository cases;
    private final EvidenceRepository evidence;
    private final Clock clock;
    private final ObjectMapper mapper = new ObjectMapper();

    public CaseEvidenceService(CaseRepository cases, EvidenceRepository evidence, Clock clock) {
        this.cases = cases;
        this.evidence = evidence;
        this.clock = clock;
    }

    // One transaction for the whole append: the row lock, the material, the revision bump and the
    // trajectory entry. Nothing here calls another service, so unlike case creation there is no
    // network call to keep outside it (docs/engineering.md:68).
    @Transactional
    public EvidenceSubmissionResponse append(
            AuthenticatedPrincipal principal, String caseId, EvidenceAppendRequest request) {
        EvidenceSourceType kind = parseKind(request);
        String text = requireText(request);
        String questionId = normaliseQuestionId(request);

        // The case row is locked for the whole append, so the revision the material records is the
        // revision the case is at when the row is written (docs/domain-model.md:36: 锁case行并校验).
        CaseRow row = cases.findCaseForUpdate(caseId);
        if (row == null || !visibleTo(principal, row)) {
            throw new CaseReadService.CaseNotVisibleException();
        }
        requireOpenInput(row);
        requireProvenance(principal, kind);

        Instant now = Instant.now(clock);
        int revision = row.inputRevision() + 1;
        evidence.insertEvidence(
                caseId,
                UUID.randomUUID().toString(),
                kind.name(),
                sourceRef(principal, kind),
                String.valueOf(revision),
                contentHash(caseId, kind, text, principal, questionId),
                revision,
                now,
                text,
                questionId,
                principal.subject(),
                principal.role().name(),
                now);
        evidence.bumpRevision(caseId, now);
        cases.insertTimeline(
                caseId,
                UUID.randomUUID().toString(),
                nextSequence(caseId),
                TimelineEventType.EVIDENCE_APPENDED.name(),
                appendedDetail(kind, text, questionId, principal),
                now,
                revision);

        return new EvidenceSubmissionResponse(caseId, revision, row.version() + 1);
    }

    private static void requireOpenInput(CaseRow row) {
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
                principal.role() != Role.CUSTOMER && kind == EvidenceSourceType.REVIEWER_VERIFICATION;
        if (!customerSubmittingAStatement && !staffRecordingAVerification) {
            throw new CaseService.ForbiddenScopeException(
                    "a " + principal.role() + " may not submit " + kind + " as its own material");
        }
    }

    private static boolean visibleTo(AuthenticatedPrincipal principal, CaseRow row) {
        if (!row.merchantId().equals(principal.merchantId())) {
            return false;
        }
        return principal.role() != Role.CUSTOMER || row.customerId().equals(principal.customerId());
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

    private int nextSequence(String caseId) {
        Integer highest = cases.highestSequence(caseId);
        return highest == null ? 1 : highest + 1;
    }
}
