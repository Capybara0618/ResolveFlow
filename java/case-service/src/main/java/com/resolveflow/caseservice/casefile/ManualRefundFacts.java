package com.resolveflow.caseservice.casefile;

import com.fasterxml.jackson.annotation.JsonProperty;
import com.resolveflow.caseservice.order.CommerceOrderLineClient;
import com.resolveflow.caseservice.policy.PolicyManifestRepository;
import com.resolveflow.caseservice.policy.PolicyRepository;
import com.resolveflow.caseservice.shopping.CommerceShoppingClient;
import com.resolveflow.shared.contract.CanonicalJson;
import java.util.List;
import java.util.UUID;
import org.springframework.stereotype.Component;
import tools.jackson.databind.ObjectMapper;

/** Server-owned preparation for the existing, narrowly scoped unshipped refund rule. */
@Component
public class ManualRefundFacts {
    private final CommerceOrderLineClient orders;
    private final CommerceShoppingClient shopping;
    private final PolicyManifestRepository manifests;
    private final PolicyRepository policies;
    private final ProposalReCheck reCheck;
    private final ObjectMapper mapper;

    public ManualRefundFacts(
            CommerceOrderLineClient orders,
            CommerceShoppingClient shopping,
            PolicyManifestRepository manifests,
            PolicyRepository policies,
            ProposalReCheck reCheck,
            ObjectMapper mapper) {
        this.orders = orders;
        this.shopping = shopping;
        this.manifests = manifests;
        this.policies = policies;
        this.reCheck = reCheck;
        this.mapper = mapper;
    }

    public record Preview(
            @JsonProperty("case_version") long caseVersion,
            @JsonProperty("input_revision") int inputRevision,
            String status,
            String message,
            @JsonProperty("amount_minor") Long amountMinor,
            @JsonProperty("policy_title") String policyTitle,
            List<String> checks) {}

    public record Prepared(Preview preview, EvidenceCitation citation, String content, List<PolicyCitation> policies) {}

    public Prepared prepare(CaseRow row) {
        var manifest = manifests.findManifest(row.caseId());
        if (manifest == null || !row.merchantId().equals(manifest.merchantId()))
            return blocked(row, "无法读取本申请对应的售后政策，请先核对政策。");
        PolicyCitation citation = null;
        String title = null;
        for (String id : manifests.findBundleIds(row.caseId())) {
            var bundle = policies.findBundle(id);
            if (bundle == null || !row.merchantId().equals(bundle.merchantId())) continue;
            for (var rule : policies.findRules(id)) {
                if (!"R-UNSHIPPED-001".equals(rule.ruleId())) continue;
                if (citation != null) return blocked(row, "存在多个未发货退款条款，请先核对适用政策。");
                citation = new PolicyCitation(id, bundle.version(), rule.ruleId(), rule.chunkId(), rule.contentHash());
                title = rule.title();
            }
        }
        if (citation == null) return blocked(row, "系统暂不能整理此类退款依据，请在详细依据中核对材料与政策。");
        var line = orders.readLineContext(row.lineId()).orElse(null);
        if (line == null
                || !row.orderId().equals(line.orderId())
                || !row.lineId().equals(line.lineId())
                || !row.merchantId().equals(line.merchantId())
                || !row.buyerId().equals(line.buyerId())) return blocked(row, "无法核对本申请的订单与付款记录，请刷新后重试。");
        if (line.paidAt() == null
                || line.linePaidAmount() <= 0
                || !"CNY".equals(line.currency())
                || line.refundableAmountMinor() != line.linePaidAmount())
            return blocked(row, "订单付款或可退款金额已变化，请先核对原退款记录。");
        final com.resolveflow.shared.shopping.FulfillmentWire.Fulfillment fulfillment;
        try {
            fulfillment = shopping.fulfillment(row.orderId(), row.merchantId(), row.buyerId());
        } catch (CommerceShoppingClient.Refused error) {
            if (error.status != 404) throw error;
            return blocked(row, "无法读取发货记录，不能按未发货退款处理。");
        }
        if (UnshippedRefundCheck.snapshotFailure(row, fulfillment) != null)
            return blocked(row, "订单未满足未发货退款条件，请核对发货状态与原始材料。");
        var refs = List.of(citation);
        var outcome = reCheck.checkContent(row, refs, "REFUND", null);
        if (!outcome.isExecutable()
                || outcome.recomputedAmountMinor() == null
                || outcome.recomputedAmountMinor() != line.linePaidAmount())
            return blocked(row, "系统复核未通过，请刷新并核对订单与政策。");
        var document = mapper.createObjectNode();
        document.set("order_payment", mapper.valueToTree(line));
        document.set("fulfillment", mapper.valueToTree(fulfillment));
        String content = CanonicalJson.canonicalize(document);
        var evidence = new EvidenceCitation(
                UUID.randomUUID().toString(),
                "manual_refund:order:" + row.orderId() + ":line:" + row.lineId(),
                "payment-" + line.version() + ":fulfillment-" + fulfillment.version(),
                CanonicalJson.contentHash(document));
        return new Prepared(
                new Preview(
                        row.version(),
                        row.inputRevision(),
                        "READY",
                        "系统已整理订单与付款依据",
                        outcome.recomputedAmountMinor(),
                        title,
                        List.of("订单已付款", "商品尚未发货", "当前整行金额可退款")),
                evidence,
                content,
                refs);
    }

    private Prepared blocked(CaseRow row, String message) {
        return new Prepared(
                new Preview(row.version(), row.inputRevision(), "BLOCKED", message, null, null, List.of()),
                null,
                null,
                List.of());
    }
}
