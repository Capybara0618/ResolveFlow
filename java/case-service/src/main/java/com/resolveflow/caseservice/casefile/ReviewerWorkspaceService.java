package com.resolveflow.caseservice.casefile;

import com.fasterxml.jackson.annotation.JsonProperty;
import com.resolveflow.caseservice.policy.PolicyManifestRepository;
import com.resolveflow.caseservice.policy.PolicyRepository;
import com.resolveflow.shared.security.AuthenticatedPrincipal;
import java.time.Clock;
import java.time.Instant;
import java.util.ArrayList;
import java.util.List;
import java.util.Objects;
import java.util.UUID;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import tools.jackson.databind.ObjectMapper;

/** Human handoff with the same revision and authorization boundaries as the core. */
@Service
public class ReviewerWorkspaceService {
    private final CaseRepository cases;
    private final AuthorizationRepository authorizations;
    private final EvidenceRepository evidence;
    private final PolicyManifestRepository manifests;
    private final PolicyRepository policies;
    private final ManualProposalService proposals;
    private final LiveAuthorization live;
    private final CaseReadService reads;
    private final Clock clock;
    private final ObjectMapper mapper;

    public ReviewerWorkspaceService(
            CaseRepository cases,
            AuthorizationRepository authorizations,
            EvidenceRepository evidence,
            PolicyManifestRepository manifests,
            PolicyRepository policies,
            ManualProposalService proposals,
            LiveAuthorization live,
            CaseReadService reads,
            Clock clock,
            ObjectMapper mapper) {
        this.cases = cases;
        this.authorizations = authorizations;
        this.evidence = evidence;
        this.manifests = manifests;
        this.policies = policies;
        this.proposals = proposals;
        this.live = live;
        this.reads = reads;
        this.clock = clock;
        this.mapper = mapper;
    }

    public record PolicyText(
            @JsonProperty("bundle_id") String bundleId,
            String version,
            @JsonProperty("rule_id") String ruleId,
            String title,
            String text,
            @JsonProperty("chunk_id") String chunkId,
            @JsonProperty("content_hash") String contentHash) {}

    public record Context(
            @JsonProperty("case_version") long caseVersion,
            @JsonProperty("input_revision") int inputRevision,
            @JsonProperty("allowed_actions") List<String> allowedActions,
            @JsonProperty("blocked_reason") String blockedReason,
            @JsonProperty("policy_rules") List<PolicyText> policyRules,
            @JsonProperty("policy_status") String policyStatus,
            @JsonProperty("review_history") List<ReviewEvent> reviewHistory,
            Execution execution) {}

    public record ReviewEvent(
            String type,
            @JsonProperty("occurred_at") Instant occurredAt,
            int revision,
            String actor,
            String reason,
            @JsonProperty("question_id") String questionId) {}

    public record Execution(
            @JsonProperty("case_status") String caseStatus,
            @JsonProperty("operation_id") String operationId,
            String outcome,
            @JsonProperty("amount_minor") Long amountMinor,
            @JsonProperty("reason_code") String reasonCode) {}

    public record Action(
            String action,
            String reason,
            @JsonProperty("evidence_refs") List<EvidenceCitation> evidenceRefs,
            @JsonProperty("policy_refs") List<PolicyCitation> policyRefs) {}

    @Transactional(readOnly = true)
    public Context read(AuthenticatedPrincipal principal, String caseId) {
        requireStaff(principal);
        CaseRow row = visible(principal, cases.findCase(caseId));
        List<PolicyText> rules = policyText(row);
        List<String> actions = allowed(row);
        String reason = row.status().isTerminal()
                ? "工单已结束，仅可查看记录"
                : consumed(row)
                        ? "退款授权已消费，输入已冻结；请查看执行结果"
                        : row.status() == CaseStatus.AUTHORIZED ? "已批准，等待退款执行" : actions.isEmpty() ? "当前状态不允许人工修改" : "";
        return new Context(
                row.version(),
                row.inputRevision(),
                actions,
                reason,
                rules,
                rules.isEmpty() ? "UNAVAILABLE" : "PINNED",
                history(row),
                execution(row));
    }

    private List<ReviewEvent> history(CaseRow row) {
        return cases.findTimeline(row.caseId()).stream()
                .filter(event -> JsonField.of(event.detail(), "reason") != null
                        || event.kind() == TimelineEventType.QUESTION_REQUIRED)
                .map(event -> new ReviewEvent(
                        event.kind().name(),
                        event.occurredAt(),
                        event.inputRevision(),
                        JsonField.of(event.detail(), "decided_by"),
                        JsonField.of(event.detail(), "reason"),
                        JsonField.of(event.detail(), "question_id")))
                .toList();
    }

    private Execution execution(CaseRow row) {
        var auth = authorizations.findLatest(row.caseId());
        String operationId = auth == null ? null : auth.plannedOperationId();
        TimelineEventRow latest = null;
        for (var event : cases.findTimeline(row.caseId())) {
            if (operationId != null
                    && operationId.equals(JsonField.of(event.detail(), "operation_id"))
                    && JsonField.of(event.detail(), "outcome") != null
                    && !Boolean.TRUE.equals(JsonField.flag(event.detail(), "ignored_as_stale"))) latest = event;
        }
        return new Execution(
                row.status().name(),
                operationId,
                latest == null ? null : JsonField.of(latest.detail(), "outcome"),
                latest == null ? null : JsonField.number(latest.detail(), "amount_minor"),
                latest == null ? null : JsonField.of(latest.detail(), "reason_code"));
    }

    private List<PolicyText> policyText(CaseRow row) {
        var manifest = manifests.findManifest(row.caseId());
        if (manifest == null || !row.merchantId().equals(manifest.merchantId())) return List.of();
        List<PolicyText> result = new ArrayList<>();
        for (String id : manifests.findBundleIds(row.caseId())) {
            var bundle = policies.findBundle(id);
            if (bundle == null || !row.merchantId().equals(bundle.merchantId())) continue;
            for (var rule : policies.findRules(id)) {
                result.add(new PolicyText(
                        id,
                        bundle.version(),
                        rule.ruleId(),
                        rule.title(),
                        rule.text(),
                        rule.chunkId(),
                        rule.contentHash()));
            }
        }
        return List.copyOf(result);
    }

    private boolean consumed(CaseRow row) {
        return row.status() == CaseStatus.EXECUTING
                || row.status() == CaseStatus.RECONCILING
                || authorizations.hasConsumed(row.caseId());
    }

    private List<String> allowed(CaseRow row) {
        if (!row.status().acceptsNewInput() || row.status() == CaseStatus.AUTHORIZED || consumed(row)) return List.of();
        List<String> actions = new ArrayList<>();
        actions.add("MANUAL_PROPOSAL");
        var auth = authorizations.findLatest(row.caseId());
        if (auth != null
                && auth.authorizationStatus() == AuthorizationStatus.PENDING_REVIEW
                && auth.inputRevision() == row.inputRevision()) {
            actions.add("REVIEW_AUTHORIZATION");
        } else {
            actions.add("REJECT");
            long questions = cases.findTimeline(row.caseId()).stream()
                    .filter(event -> event.kind() == TimelineEventType.QUESTION_REQUIRED)
                    .count();
            if (row.status() != CaseStatus.WAITING_CUSTOMER
                    && questions < 2
                    && (row.expiresAt() == null || Instant.now(clock).isBefore(row.expiresAt()))) {
                actions.add("REQUEST_INFO");
            }
        }
        return List.copyOf(actions);
    }

    @Transactional
    public CaseSnapshotResponse act(AuthenticatedPrincipal principal, String caseId, String ifMatch, Action request) {
        requireStaff(principal);
        if (ifMatch == null || !ifMatch.matches("\"[1-9][0-9]{0,15}\"")) {
            throw new CaseService.SemanticInvalidException("If-Match must contain the quoted case version");
        }
        CaseRow row = visible(principal, cases.findCaseForUpdate(caseId));
        if (row.version() != Long.parseLong(ifMatch.substring(1, ifMatch.length() - 1))) {
            throw new CaseStateConflictException("工单已更新，请重新核对材料后提交");
        }
        if (!List.of("MANUAL_PROPOSAL", "REJECT", "REQUEST_INFO")
                .contains(request.action() == null ? "" : request.action())) {
            throw new CaseService.SemanticInvalidException("unsupported reviewer action");
        }
        if (!allowed(row).contains(request.action())) {
            throw new CaseStateConflictException("当前状态不允许该操作，请刷新工单查看最新进度");
        }
        if (request.reason() == null
                || request.reason().isBlank()
                || request.reason().length() > 1000) {
            throw new CaseService.SemanticInvalidException("reason must contain 1–1000 characters");
        }
        if ("MANUAL_PROPOSAL".equals(request.action())) {
            requireActualEvidence(row, request.evidenceRefs());
            proposals.submit(
                    principal,
                    caseId,
                    new ManualProposalRequest(
                            "REFUND",
                            request.evidenceRefs(),
                            request.policyRefs(),
                            request.reason().trim()));
        } else {
            decideWithoutAuthorization(principal, row, request);
        }
        return reads.read(principal, caseId);
    }

    private void requireActualEvidence(CaseRow row, List<EvidenceCitation> refs) {
        if (refs == null || refs.isEmpty() || refs.size() > 20) {
            throw new CaseService.SemanticInvalidException("请选择本工单的材料作为依据");
        }
        var material = evidence.findRecent(row.caseId(), CaseEvidenceService.MAX_RECORDS);
        for (var ref : refs) {
            if (ref == null
                    || material.stream()
                            .noneMatch(item -> Objects.equals(item.evidenceId(), ref.observationId())
                                    && Objects.equals(item.sourceRef(), ref.sourceRef())
                                    && Objects.equals(item.sourceVersion(), ref.sourceVersion())
                                    && Objects.equals(item.contentHash(), ref.contentHash()))) {
                throw new CaseService.SemanticInvalidException("材料引用不属于当前工单，或来源版本已变化");
            }
        }
    }

    private void decideWithoutAuthorization(AuthenticatedPrincipal principal, CaseRow row, Action request) {
        Instant now = Instant.now(clock);
        boolean reject = "REJECT".equals(request.action());
        CaseStatus next = reject ? CaseStatus.CLOSED_REJECTED : CaseStatus.WAITING_CUSTOMER;
        // Advance the revision as well as state: in-flight Agent callbacks must not overwrite a human handoff.
        if (cases.advanceRevision(row.caseId(), row.inputRevision(), row.inputRevision() + 1, next.name(), now) != 1) {
            throw new CaseStateConflictException("工单已更新，未记录本次决定");
        }
        live.revoke(row.caseId(), "人工处理：" + request.reason().trim(), now);
        var detail = mapper.createObjectNode();
        detail.put("origin", "HUMAN");
        detail.put("decision", request.action());
        detail.put("reason", request.reason().trim());
        detail.put("decided_by", principal.subject());
        detail.put("decided_role", principal.role().name());
        detail.put("status", next.name());
        if (reject) {
            cases.releaseActiveSlot(row.merchantId(), row.lineId());
        } else {
            detail.put("question_id", UUID.randomUUID().toString());
            detail.putArray("questions")
                    .addObject()
                    .put("field", "additional_evidence")
                    .put("prompt", request.reason().trim());
        }
        cases.insertTimeline(
                row.caseId(),
                UUID.randomUUID().toString(),
                cases.nextTimelineSequence(row.caseId()),
                (reject ? TimelineEventType.CASE_CLOSED : TimelineEventType.QUESTION_REQUIRED).name(),
                detail.toString(),
                now,
                row.inputRevision() + 1);
    }

    private static void requireStaff(AuthenticatedPrincipal principal) {
        CaseStaff.require(principal, "review workspace is available to merchant staff only");
    }

    private static CaseRow visible(AuthenticatedPrincipal principal, CaseRow row) {
        if (row == null || !row.visibleTo(principal)) throw new CaseReadService.CaseNotVisibleException();
        return row;
    }
}
