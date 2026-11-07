package com.resolveflow.caseservice.casefile;

import com.resolveflow.caseservice.shopping.CommerceShoppingClient;
import java.util.List;
import org.springframework.stereotype.Component;
import tools.jackson.databind.ObjectMapper;

/** Fresh authoritative facts for the narrowly scoped R-UNSHIPPED-001 policy. */
@Component
public class UnshippedRefundCheck {
    private final CommerceShoppingClient commerce;
    private final ProposalRepository proposals;
    private final ObjectMapper mapper;

    public UnshippedRefundCheck(CommerceShoppingClient commerce, ProposalRepository proposals, ObjectMapper mapper) {
        this.commerce = commerce;
        this.proposals = proposals;
        this.mapper = mapper;
    }

    public String failure(CaseRow row, List<PolicyCitation> citations) {
        if (citations.stream().noneMatch(c -> "R-UNSHIPPED-001".equals(c.ruleId()))) return null;
        return currentFailure(row);
    }

    /** Read the exact proposal fixed by the authorization, never the latest unrelated proposal. */
    public String failure(CaseRow row, AuthorizationRepository.StoredAuthorization authorization) {
        var proposal = proposals.findByProposalId(authorization.proposalId());
        if (proposal == null
                || !row.caseId().equals(proposal.caseId())
                || proposal.inputRevision() != row.inputRevision()) {
            return "the authorization's original proposal is missing or no longer belongs to this input";
        }
        var refs = proposal.payloadAsJson(mapper).get("policy_refs");
        if (refs == null) return null;
        for (var citation : refs) {
            if ("R-UNSHIPPED-001".equals(citation.path("rule_id").stringValue())) {
                if (proposal.origin() == ProposalOrigin.HUMAN
                        && !proposal.contentHash(mapper).equals(proposal.payloadHash())) {
                    return "the original unshipped proposal's content hash changed";
                }
                return currentFailure(row);
            }
        }
        return null;
    }

    private String currentFailure(CaseRow row) {
        final com.resolveflow.shared.shopping.FulfillmentWire.Fulfillment snapshot;
        try {
            snapshot = commerce.fulfillment(row.orderId(), row.merchantId(), row.buyerId());
        } catch (CommerceShoppingClient.Refused error) {
            if (error.status != 404) throw error;
            return "未发货退款依据不存在：不能把缺失物流视为未发货";
        }
        return snapshotFailure(row, snapshot);
    }

    static String snapshotFailure(CaseRow row, com.resolveflow.shared.shopping.FulfillmentWire.Fulfillment snapshot) {
        if (snapshot == null
                || !row.orderId().equals(snapshot.orderId())
                || !snapshot.synthetic()
                || !"NOT_SHIPPED".equals(snapshot.status())
                || !Long.valueOf(1).equals(snapshot.version())
                || snapshot.updatedAt() == null
                || snapshot.lines() == null) {
            return "未发货退款依据已变化或无法核验：请重新调查当前履约事实";
        }
        var matching = snapshot.lines().stream()
                .filter(line -> row.lineId().equals(line.lineId()))
                .toList();
        if (matching.size() != 1) return "未发货退款依据缺少唯一的当前订单行";
        var line = matching.get(0);
        if (!"NOT_SHIPPED".equals(line.status())
                || !"UNKNOWN".equals(line.carrierConclusion())
                || !Long.valueOf(1).equals(line.sourceVersion())
                || line.events() == null
                || line.events().size() != 1
                || !"ORDER_PAID".equals(line.events().get(0).code())
                || line.events().get(0).sourceVersion() != 1
                || line.events().get(0).occurredAt() == null) {
            return "未发货退款依据的行状态、版本或付款事件已变化：请重新调查";
        }
        return null;
    }
}
