package com.resolveflow.caseservice.casefile;

import com.fasterxml.jackson.annotation.JsonProperty;
import com.resolveflow.caseservice.order.CommerceOrderLineClient;
import com.resolveflow.shared.security.AuthenticatedPrincipal;
import com.resolveflow.shared.security.Role;
import java.nio.charset.StandardCharsets;
import java.time.Clock;
import java.time.Instant;
import java.util.ArrayList;
import java.util.Base64;
import java.util.List;
import java.util.UUID;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import tools.jackson.databind.ObjectMapper;

/** Customer projection deliberately never serializes proposal, authorization, tool records or staff actors. */
@Service
public class CustomerCaseService {
    private final CaseRepository cases;
    private final CustomerCaseRepository lists;
    private final EvidenceRepository evidence;
    private final AuthorizationRepository authorizations;
    private final CaseEvidenceService writes;
    private final CommerceOrderLineClient commerce;
    private final Clock clock;
    private final ObjectMapper json;

    public CustomerCaseService(
            CaseRepository cases,
            CustomerCaseRepository lists,
            EvidenceRepository evidence,
            AuthorizationRepository authorizations,
            CaseEvidenceService writes,
            CommerceOrderLineClient commerce,
            Clock clock,
            ObjectMapper json) {
        this.cases = cases;
        this.lists = lists;
        this.evidence = evidence;
        this.authorizations = authorizations;
        this.writes = writes;
        this.commerce = commerce;
        this.clock = clock;
        this.json = json;
    }

    public record Summary(
            @JsonProperty("case_id") String caseId,
            CaseStatus status,
            @JsonProperty("line_id") String lineId,
            @JsonProperty("order_id") String orderId,
            String description,
            long version,
            @JsonProperty("created_at") Instant createdAt,
            @JsonProperty("updated_at") Instant updatedAt,

            @JsonProperty("merchant_id")
            @com.fasterxml.jackson.annotation.JsonInclude(com.fasterxml.jackson.annotation.JsonInclude.Include.NON_NULL)
            String merchantId) {}

    public record PageMeta(@JsonProperty("next_cursor") String nextCursor, int limit) {}

    public record Page(List<Summary> items, PageMeta page) {}

    public record Material(
            String id,
            String text,
            @JsonProperty("submitted_at") Instant submittedAt,
            @JsonProperty("question_id") String questionId,
            @JsonProperty("verification_result") String verificationResult) {}

    public record Question(
            @JsonProperty("question_id") String questionId,
            List<String> prompts,
            String status,
            @JsonProperty("asked_at") Instant askedAt,
            @JsonProperty("expires_at") Instant expiresAt,
            List<Material> answers) {}

    public record Result(
            CaseStatus status,
            String message,
            @JsonProperty("amount_minor") Long amountMinor,
            String currency,
            @JsonProperty("public_reason") String publicReason) {}

    public record Progress(
            String type, @JsonProperty("occurred_at") Instant occurredAt, String summary) {}

    public record Detail(
            @JsonProperty("case") Summary caseSummary,
            @JsonProperty("input_revision") int inputRevision,
            @JsonProperty("allowed_actions") List<String> allowedActions,
            @JsonProperty("blocked_reason") String blockedReason,
            List<Material> materials,
            List<Question> questions,
            Result result,
            List<Progress> timeline) {}

    public record Line(
            @JsonProperty("order_line") CommerceOrderLineClient.OrderLineSummary orderLine,
            Summary application,
            @JsonProperty("can_apply") boolean canApply,
            @JsonProperty("blocked_reason") String blockedReason) {}

    public record Answer(@JsonProperty("question_id") String questionId, String text) {}

    private Summary summary(CaseRow row) {
        return summary(row, false);
    }

    private Summary summary(CaseRow row, boolean includeMerchant) {
        return new Summary(
                row.caseId(),
                row.status(),
                row.lineId(),
                row.orderId(),
                row.description(),
                row.version(),
                row.createdAt(),
                row.updatedAt(),
                includeMerchant ? row.merchantId() : null);
    }

    static void requireCustomer(AuthenticatedPrincipal p) {
        if (p.role() != Role.CUSTOMER)
            throw new CaseService.ForbiddenScopeException("this workspace belongs to a customer");
    }

    private static ReviewQueueService.InvalidPageException invalid(String message) {
        return new ReviewQueueService.InvalidPageException(message);
    }

    private CaseRow visible(AuthenticatedPrincipal p, CaseRow row) {
        if (row == null || !row.visibleTo(p)) throw new CaseReadService.CaseNotVisibleException();
        return row;
    }

    public Page list(AuthenticatedPrincipal p, String view, String line, String cursor, Integer size) {
        requireCustomer(p);
        view = view == null ? "ALL" : view;
        int limit = size == null ? 20 : size;
        if (!List.of("ALL", "WAITING", "PROCESSING", "REVIEW", "CLOSED").contains(view) || limit < 1 || limit > 100)
            throw invalid("view or limit is invalid");
        if (line != null && (line.isBlank() || line.length() > 64))
            throw invalid("line_id must contain 1-64 characters");
        Instant before = null;
        String id = null;
        if (cursor != null) {
            try {
                if (cursor.isBlank() || cursor.length() > 2048) throw new IllegalArgumentException();
                var node = json.readTree(new String(Base64.getUrlDecoder().decode(cursor), StandardCharsets.UTF_8));
                if (p.isPlatformBuyer()
                        && !p.buyerId().equals(node.path("buyer_id").asString())) throw new IllegalArgumentException();
                if (!view.equals(node.get("view").stringValue())
                        || !java.util.Objects.equals(
                                line,
                                node.get("line").isNull()
                                        ? null
                                        : node.get("line").stringValue())) throw new IllegalArgumentException();
                before = Instant.parse(node.get("time").stringValue());
                id = node.get("id").stringValue();
                if (!UUID.fromString(id).toString().equals(id)) throw new IllegalArgumentException();
            } catch (RuntimeException error) {
                throw invalid("cursor is invalid or belongs to another filter");
            }
        }
        var rows = p.isPlatformBuyer()
                ? lists.listBuyer(p.buyerId(), view, line, before, id, limit + 1)
                : lists.list(p.merchantId(), p.customerId(), view, line, before, id, limit + 1);
        var page = rows.stream().limit(limit).toList();
        String next = null;
        if (rows.size() > limit) {
            var last = page.getLast();
            var node = json.createObjectNode();
            if (p.isPlatformBuyer()) node.put("buyer_id", p.buyerId());
            node.put("view", view);
            node.put("line", line);
            node.put("time", last.updatedAt().toString());
            node.put("id", last.caseId());
            next = Base64.getUrlEncoder()
                    .withoutPadding()
                    .encodeToString(node.toString().getBytes(StandardCharsets.UTF_8));
        }
        return new Page(
                page.stream().map(row -> summary(row, p.isPlatformBuyer())).toList(), new PageMeta(next, limit));
    }

    public Line line(AuthenticatedPrincipal p, String lineId) {
        requireCustomer(p);
        if (lineId.isBlank() || lineId.length() > 64) throw invalid("invalid line_id");
        var lines = commerce.listByLine(p, lineId).items();
        if (lines.size() != 1) throw new CaseReadService.CaseNotVisibleException();
        var line = lines.getFirst();
        var context = commerce.readLineContext(lineId).orElseThrow(CaseReadService.CaseNotVisibleException::new);
        if (!p.merchantId().equals(context.merchantId()) || !p.customerId().equals(context.customerId()))
            throw new CaseReadService.CaseNotVisibleException();
        var related = lists.related(p.merchantId(), p.customerId(), lineId);
        String refusal = related != null && !related.status().isTerminal()
                ? "该订单行已有处理中申请，请查看当前申请"
                : related != null && related.status() == CaseStatus.CLOSED_SUCCESS
                        ? "该订单行已完成模拟退款"
                        : !"PAID".equals(context.orderStatus())
                                ? "订单当前不是已支付状态"
                                : context.refundableAmountMinor() < context.linePaidAmount()
                                        ? "订单当前可退金额不足整行全额，请联系商家"
                                        : "";
        return new Line(line, related == null ? null : summary(related), refusal.isEmpty(), refusal);
    }

    @Transactional(readOnly = true)
    public Detail read(AuthenticatedPrincipal p, String caseId) {
        requireCustomer(p);
        return detail(visible(p, cases.findCase(caseId)));
    }

    @Transactional
    public Detail answer(AuthenticatedPrincipal p, String caseId, String ifMatch, Answer request) {
        requireCustomer(p);
        if (ifMatch == null || !ifMatch.matches("\"[1-9][0-9]{0,15}\""))
            throw new CaseService.SemanticInvalidException("If-Match must contain the quoted case version");
        var row = visible(p, cases.findCaseForUpdate(caseId));
        if (row.version() != Long.parseLong(ifMatch.substring(1, ifMatch.length() - 1)))
            throw new CaseStateConflictException("申请已更新，请刷新后回答");
        var question = cases.findTimeline(caseId).stream()
                .filter(e -> e.kind() == TimelineEventType.QUESTION_REQUIRED)
                .reduce((a, b) -> b)
                .orElse(null);
        if (row.status() != CaseStatus.WAITING_CUSTOMER
                || question == null
                || request.questionId() == null
                || request.questionId().isBlank()
                || !request.questionId().equals(JsonField.of(question.detail(), "question_id")))
            throw new CaseStateConflictException("该问题已不是当前待回答问题");
        if (!Instant.now(clock).isBefore(ReviewQuestionService.answerDeadline(row, question)))
            throw new CaseStateConflictException("补证期限已过，请等待商家处理");
        writes.append(p, caseId, new EvidenceAppendRequest(request.questionId(), request.text(), "CUSTOMER_STATEMENT"));
        return detail(cases.findCase(caseId));
    }

    private Detail detail(CaseRow row) {
        var events = cases.findTimeline(row.caseId());
        var all = evidence.findRecent(row.caseId(), CaseEvidenceService.MAX_RECORDS);
        List<Material> materials = new ArrayList<>();
        for (int i = all.size() - 1; i >= 0; i--) {
            var e = all.get(i);
            if (e.kind() != EvidenceSourceType.CUSTOMER_STATEMENT) continue;
            String verdict = all.stream()
                    .filter(v -> e.evidenceId().equals(v.reviewedEvidenceId()))
                    .map(EvidenceRepository.EvidenceRow::verificationResult)
                    .filter(java.util.Objects::nonNull)
                    .findFirst()
                    .orElse(null);
            materials.add(new Material(e.evidenceId(), e.content(), e.createdAt(), e.questionId(), verdict));
        }
        var asked = events.stream()
                .filter(e -> e.kind() == TimelineEventType.QUESTION_REQUIRED)
                .toList();
        List<Question> questions = new ArrayList<>();
        boolean pending = false;
        for (var event : asked) {
            String q = JsonField.of(event.detail(), "question_id");
            List<String> prompts = new ArrayList<>();
            try {
                var fields = json.readTree(event.detail()).get("questions");
                if (fields != null && fields.isArray())
                    for (var field : fields) {
                        var prompt = field.get("prompt");
                        if (prompt != null
                                && prompt.isString()
                                && !prompt.stringValue().isBlank()) prompts.add(prompt.stringValue());
                    }
            } catch (RuntimeException ignored) {
                /* Historical unreadable questions remain unavailable. */
            }
            var answers = q == null
                    ? List.<Material>of()
                    : materials.stream().filter(m -> q.equals(m.questionId())).toList();
            var deadline = ReviewQuestionService.answerDeadline(row, event);
            String state = !answers.isEmpty()
                    ? "ANSWERED"
                    : q == null || prompts.isEmpty()
                            ? "UNAVAILABLE"
                            : row.status() != CaseStatus.WAITING_CUSTOMER || event != asked.getLast()
                                    ? "CLOSED"
                                    : !Instant.now(clock).isBefore(deadline) ? "EXPIRED" : "PENDING";
            pending |= state.equals("PENDING");
            questions.add(new Question(q, prompts, state, event.occurredAt(), deadline, answers));
        }
        boolean consumed = authorizations.hasConsumed(row.caseId());
        List<String> allowed = new ArrayList<>();
        if (row.status().acceptsNewInput() && !consumed) {
            allowed.add("CANCEL");
            if (row.status() == CaseStatus.WAITING_CUSTOMER) {
                if (pending) allowed.add("ANSWER");
            } else allowed.add("APPEND_EVIDENCE");
        }
        String blocked = consumed
                ? "退款已进入执行阶段，不能撤销或修改材料"
                : row.status().isTerminal()
                        ? "申请已结束，仅可查看记录"
                        : row.status() == CaseStatus.WAITING_CUSTOMER && !pending ? "当前问题已过期或缺少可回答记录，请等待商家处理" : "";
        Long amount = null;
        String reason = null;
        var auth = authorizations.findLatest(row.caseId());
        if (auth != null
                && (consumed || row.status() == CaseStatus.AUTHORIZED || row.status() == CaseStatus.CLOSED_SUCCESS))
            amount = auth.amountMinor();
        for (var e : events) {
            if ((e.kind() == TimelineEventType.AUTHORIZATION_DECIDED || e.kind() == TimelineEventType.CASE_CLOSED)
                    && JsonField.of(e.detail(), "reason") != null) reason = JsonField.of(e.detail(), "reason");
        }
        if (row.status() == CaseStatus.WAITING_CUSTOMER) {
            reason = questions.isEmpty()
                    ? null
                    : String.join("；", questions.getLast().prompts());
        } else if (!row.status().isTerminal() && !consumed && row.status() != CaseStatus.AUTHORIZED) {
            reason = null;
        }
        String message = resultMessage(row.status());
        if (consumed && row.status() == CaseStatus.PENDING_REVIEW && auth != null) {
            var execution = events.stream()
                    .filter(e -> e.kind() == TimelineEventType.EXECUTION_UPDATED
                            && auth.plannedOperationId().equals(JsonField.of(e.detail(), "operation_id"))
                            && !Boolean.TRUE.equals(JsonField.flag(e.detail(), "ignored_as_stale")))
                    .reduce((a, b) -> b)
                    .orElse(null);
            if (execution != null && "FAILED".equals(JsonField.of(execution.detail(), "outcome")))
                message = "模拟退款执行失败，商家正在处理；当前申请不能修改或重复执行";
        }
        var result = new Result(row.status(), message, amount, "CNY", reason);
        var timeline = events.stream()
                .map(e -> new Progress(e.kind().name(), e.occurredAt(), progress(e.kind())))
                .toList();
        return new Detail(
                summary(row),
                row.inputRevision(),
                List.copyOf(allowed),
                blocked,
                List.copyOf(materials),
                List.copyOf(questions),
                result,
                timeline);
    }

    private static String resultMessage(CaseStatus status) {
        return switch (status) {
            case QUEUED -> "申请已收到，等待调查";
            case ANALYZING -> "正在核对订单、材料和政策";
            case WAITING_CUSTOMER -> "商家需要您补充说明";
            case PENDING_REVIEW -> "等待商家审核";
            case AUTHORIZED -> "商家已批准，等待模拟退款执行";
            case EXECUTING -> "模拟退款正在执行，尚未确认完成";
            case RECONCILING -> "退款结果待确认，请勿重复申请";
            case CLOSED_SUCCESS -> "模拟退款已完成";
            case CLOSED_REJECTED -> "申请未获批准";
            case CANCELLED -> "申请已撤销";
        };
    }

    private static String progress(TimelineEventType type) {
        return switch (type) {
            case CASE_CREATED -> "退款申请已提交";
            case EVIDENCE_APPENDED -> "提交材料或核验记录已更新";
            case AGENT_STARTED -> "开始调查";
            case QUESTION_REQUIRED -> "需要补充说明";
            case PROPOSAL_READY, APPROVAL_REQUIRED -> "调查完成，等待商家核对";
            case AUTHORIZATION_DECIDED -> "商家审核决定已记录";
            case EXECUTION_UPDATED -> "模拟退款执行状态已更新";
            case AGENT_FAILED -> "调查暂未完成，由商家继续处理";
            case CASE_CLOSED -> "申请处理已结束";
        };
    }
}
