package com.resolveflow.caseservice.casefile;

import com.resolveflow.shared.security.AuthenticatedPrincipal;
import java.time.Clock;
import java.time.Instant;
import java.util.List;
import java.util.UUID;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import tools.jackson.databind.ObjectMapper;
import tools.jackson.databind.node.ObjectNode;

/**
 * A person's proposal (C03.3c-1, docs/core-contracts.md:36).
 *
 * <p>It exists because a run is not always able to propose: the agent can fail, be refused by the re-check,
 * or hand the case over, and a human then has to be able to say "this is what I read, and this is what should
 * be paid". What the human supplies is what they rely on; what they do not supply is the amount, because the
 * amount is recomputed from Commerce here exactly as it is for a run's proposal.
 *
 * <p>Three decisions shape this class:
 *
 * <ul>
 *   <li><b>The submission moves the input revision.</b> A person's citation set is new decision input, not a
 *       comment on the run's, so the case advances a revision and the response reports both versions. That is
 *       what makes the previous proposal and the previous authorisation read as stale rather than being
 *       quietly reinterpreted.
 *   <li><b>It checks before it records.</b> The submission goes through the same content check a run's
 *       proposal does ({@link ProposalReCheck#checkContent}), and a refusal answers the caller instead of
 *       being stored: a person is still connected and can fix what they wrote, whereas a run's delivery is a
 *       durable event that has to be recorded whatever it said. A refused submission therefore changes
 *       nothing at all.
 *   <li><b>A live authorisation is superseded, never left approved.</b> An authorisation is fixed to the
 *       revision it was created for, so the one from the previous revision is revoked in the same transaction
 *       that creates its replacement (docs/domain-model.md:36). The unique key on the live marker is what
 *       makes "one live authorisation" a property of the schema; this class is the writer that respects it.
 * </ul>
 */
@Service
public class ManualProposalService {

    private final CaseRepository cases;
    private final ProposalService proposals;
    private final ProposalReCheck reCheck;
    private final LiveAuthorization liveAuthorisations;
    private final AuthorizationService authorizationService;
    private final Clock clock;
    private final ObjectMapper mapper;

    public ManualProposalService(
            CaseRepository cases,
            ProposalService proposals,
            ProposalReCheck reCheck,
            LiveAuthorization liveAuthorisations,
            AuthorizationService authorizationService,
            Clock clock,
            ObjectMapper mapper) {
        this.cases = cases;
        this.proposals = proposals;
        this.reCheck = reCheck;
        this.liveAuthorisations = liveAuthorisations;
        this.authorizationService = authorizationService;
        this.clock = clock;
        this.mapper = mapper;
    }

    @Transactional
    public ManualProposalResponse submit(
            AuthenticatedPrincipal principal, String caseId, ManualProposalRequest request) {
        CaseStaff.require(
                principal,
                "a manual proposal is merchant staff's account of the case; a customer-scoped token"
                        + " may not submit one");
        String action = requireRefundAction(request.action());
        String reason = requireReason(request.reason());
        reCheck.requireEvidenceRefs(request.evidenceRefs(), 1, MAX_EVIDENCE_REFS);
        requirePolicyRefs(request.policyRefs());

        CaseRow row = cases.findCaseForUpdate(caseId);
        if (row == null || !row.visibleTo(principal)) {
            throw new CaseReadService.CaseNotVisibleException();
        }
        if (!row.status().acceptsNewInput()) {
            throw new CaseStateConflictException("this case is " + row.status()
                    + ": its input is frozen, so a new revision cannot be started (docs/domain-model.md:36)");
        }

        ProposalReCheck.Outcome outcome = reCheck.checkContent(row, request.policyRefs(), action, null);
        if (!outcome.isExecutable()) {
            throw refusal(outcome);
        }

        Instant now = Instant.now(clock);
        int revision = row.inputRevision() + 1;
        if (cases.advanceRevision(row.caseId(), row.inputRevision(), revision, CaseStatus.PENDING_REVIEW.name(), now)
                != 1) {
            throw new CaseStateConflictException(
                    "this case moved while the proposal was being checked;" + " nothing was recorded");
        }
        CaseRow advanced = cases.findCase(row.caseId());
        String proposalId = UUID.randomUUID().toString();
        proposals.recordManual(
                advanced, proposalId, document(advanced, proposalId, action, reason, request), outcome, principal, now);

        String superseded = supersedeLiveAuthorisation(advanced, proposalId, now);
        AuthorizationService.Created created = authorizationService.create(advanced, outcome, proposalId, now);
        cases.insertTimeline(
                advanced.caseId(),
                UUID.randomUUID().toString(),
                cases.nextTimelineSequence(advanced.caseId()),
                TimelineEventType.PROPOSAL_READY.name(),
                proposalDetail(advanced, proposalId, outcome, principal, superseded),
                now,
                advanced.inputRevision());
        if (created != null) {
            cases.insertTimeline(
                    advanced.caseId(),
                    UUID.randomUUID().toString(),
                    cases.nextTimelineSequence(advanced.caseId()),
                    TimelineEventType.APPROVAL_REQUIRED.name(),
                    authorisationDetail(created),
                    now,
                    advanced.inputRevision());
        }
        return new ManualProposalResponse(advanced.caseId(), proposalId, advanced.inputRevision(), advanced.version());
    }

    /**
     * The document this service records as the proposal.
     *
     * <p>Built here rather than echoed from the request, because the request is not a proposal: the caller
     * named what they rely on, and this service supplies the members a proposal has and a person's submission
     * does not — the protocol version, the id, the revision it belongs to, and the action under the proposal's
     * own member name. The author's {@code reason} becomes the proposal's {@code summary}: there is no second
     * free-text member saying the same thing, and {@code origin}/{@code authored_by} live in their own columns
     * rather than being duplicated here.
     */
    private ObjectNode document(
            CaseRow row, String proposalId, String action, String reason, ManualProposalRequest request) {
        ObjectNode document = mapper.createObjectNode();
        document.put("schema_version", 2);
        document.put("proposal_id", proposalId);
        document.put("case_id", row.caseId());
        document.put("input_revision", row.inputRevision());
        document.put("recommended_action", action);
        document.put("summary", reason);
        var evidence = document.putArray("evidence_refs");
        for (EvidenceCitation citation : request.evidenceRefs()) {
            ObjectNode node = evidence.addObject();
            if (citation.observationId() != null) {
                node.put("observation_id", citation.observationId());
            }
            node.put("source_ref", citation.sourceRef());
            if (citation.sourceVersion() != null) {
                node.put("source_version", citation.sourceVersion());
            }
            if (citation.contentHash() != null) {
                node.put("content_hash", citation.contentHash());
            }
        }
        var policies = document.putArray("policy_refs");
        for (PolicyCitation citation : request.policyRefs()) {
            ObjectNode node = policies.addObject();
            node.put("bundle_id", citation.bundleId());
            node.put("version", citation.version());
            node.put("rule_id", citation.ruleId());
            node.put("chunk_id", citation.chunkId());
            node.put("content_hash", citation.contentHash());
        }
        return document;
    }

    /**
     * Retire the case's live authorisation, in the transaction that replaces it.
     *
     * <p>The rule itself lives in {@link LiveAuthorization}, because writing new input is not something only
     * this route does: material and verifications retire an approval for the same reason. What is specific to
     * this route is the reason it records — the id of the proposal that replaced it — so the sentence a later
     * reader finds on the old row names the act rather than saying "something changed".
     */
    private String supersedeLiveAuthorisation(CaseRow row, String proposalId, Instant now) {
        return liveAuthorisations.revoke(
                row.caseId(),
                "superseded by proposal " + proposalId + " at input revision " + row.inputRevision(),
                now);
    }

    private String proposalDetail(
            CaseRow row,
            String proposalId,
            ProposalReCheck.Outcome outcome,
            AuthenticatedPrincipal principal,
            String superseded) {
        ObjectNode detail = mapper.createObjectNode();
        detail.put("origin", ProposalOrigin.HUMAN.name());
        detail.put("proposal_id", proposalId);
        detail.put("input_revision", row.inputRevision());
        detail.put("recommended_action", ExecutableAction.REFUND.wire());
        detail.put("recomputed_amount_minor", outcome.recomputedAmountMinor());
        detail.put("authored_by", principal.subject());
        detail.put("authored_role", principal.role().name());
        if (superseded != null) {
            detail.put("superseded_authorization_id", superseded);
        }
        return com.resolveflow.shared.contract.CanonicalJson.canonicalize(detail);
    }

    private String authorisationDetail(AuthorizationService.Created created) {
        ObjectNode detail = mapper.createObjectNode();
        detail.put("authorization_id", created.authorizationId());
        detail.put("authorization_version", created.authorizationVersion());
        detail.put("planned_operation_id", created.plannedOperationId());
        detail.put("amount_minor", created.amountMinor());
        detail.put("payload_hash", created.payloadHash());
        return com.resolveflow.shared.contract.CanonicalJson.canonicalize(detail);
    }

    /** A content refusal, answered to the caller: 422 when the submission is at fault, 409 when the world is. */
    private static RuntimeException refusal(ProposalReCheck.Outcome outcome) {
        String reason = outcome.refusalReason() == null ? "the proposal was refused" : outcome.refusalReason();
        return outcome.refusalKind() == ProposalReCheck.Outcome.RefusalKind.WORLD
                ? new CaseStateConflictException(reason)
                : new CaseService.SemanticInvalidException(reason);
    }

    /**
     * The action has to be one this service can execute.
     *
     * <p>Parsed as a recommendation first (an unknown action is a 422 naming it) and then narrowed to the one
     * action the core executes: a proposal to {@code MANUAL_REVIEW} or {@code REJECT} is a proposal to route
     * the case, and there is nothing for an authorisation to carry. {@link ExecutableAction#of} is deliberately
     * not used to read the request — it reads stored rows, and an unknown request value is not a database
     * problem.
     */
    private static String requireRefundAction(String action) {
        if (action == null) {
            throw new CaseService.SemanticInvalidException("action is required");
        }
        RecommendedAction recommended = RecommendedAction.of(action);
        if (recommended != RecommendedAction.REFUND) {
            throw new CaseService.SemanticInvalidException(
                    "a manual proposal can only ask for REFUND; this" + " service has nothing that executes " + action);
        }
        return ExecutableAction.REFUND.wire();
    }

    private static void requirePolicyRefs(List<PolicyCitation> refs) {
        if (refs == null || refs.isEmpty() || refs.size() > 10) {
            throw new CaseService.SemanticInvalidException(
                    "policy_refs must hold between 1 and 10 references: a refund has to cite the policy"
                            + " it relies on, and that citation is what this service can check");
        }
    }

    private static String requireReason(String reason) {
        if (reason == null || reason.isBlank()) {
            throw new CaseService.SemanticInvalidException(
                    "reason is required; a proposal nobody explained is one a reviewer cannot weigh");
        }
        if (reason.length() > 1000) {
            throw new CaseService.SemanticInvalidException("reason must be at most 1000 characters");
        }
        return reason;
    }

    private static final int MAX_EVIDENCE_REFS = 32;
}
