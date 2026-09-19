package com.resolveflow.caseservice.casefile;

import com.resolveflow.caseservice.policy.PolicyManifest;
import com.resolveflow.caseservice.policy.PolicyManifestRepository;
import com.resolveflow.shared.contract.CanonicalJson;
import java.time.Instant;
import java.util.List;
import java.util.UUID;
import org.springframework.stereotype.Component;
import org.springframework.transaction.annotation.Transactional;
import tools.jackson.databind.ObjectMapper;
import tools.jackson.databind.node.ObjectNode;

/**
 * The one transaction that opens a case.
 *
 * <p>It is a separate component because the transaction must contain exactly the writes and nothing
 * else: the Commerce call that decides whether the line is the caller's happens before this is entered,
 * so no network call is ever inside it (docs/engineering.md:68).
 *
 * <p>Everything a reader would expect to have happened together is here together: the case, what the
 * customer asked for, the slot that makes a second open case impossible, the policy version it is pinned
 * to, the first trajectory entry, and the stored idempotent answer. A partial version of these would describe a case that never
 * happened.
 */
@Component
public class CaseWriter {

    /** The facts one create writes, gathered so the transaction has one input. */
    public record CaseWrite(
            String caseId,
            String merchantId,
            String customerId,
            String orderId,
            String lineId,
            List<RequestedAction> actions,
            String description,
            String idempotencyKey,
            String requestHash,
            PolicyManifest manifest,
            Instant now) {}

    private final CaseRepository cases;
    private final PolicyManifestRepository manifests;
    private final ObjectMapper mapper = new ObjectMapper();

    public CaseWriter(CaseRepository cases, PolicyManifestRepository manifests) {
        this.cases = cases;
        this.manifests = manifests;
    }

    @Transactional
    public CaseService.Created writeCase(CaseWrite write) {
        cases.insertCase(
                write.caseId(),
                write.merchantId(),
                write.customerId(),
                write.orderId(),
                write.lineId(),
                CaseStatus.QUEUED.name(),
                1,
                1L,
                null,
                write.now(),
                write.now());
        for (RequestedAction action : write.actions()) {
            cases.insertRequestedAction(write.caseId(), action.name());
        }
        cases.insertSlot(write.merchantId(), write.lineId(), write.caseId(), write.now());
        // The policy the case is pinned to is written with the case: a case exists under a policy or it
        // does not exist, and a later import must not be able to change what an open case is decided by.
        manifests.insertManifest(
                write.caseId(),
                write.manifest().manifestHash(),
                write.manifest().safetyEpoch(),
                write.manifest().effectiveFrom(),
                write.manifest().effectiveTo(),
                write.manifest().selectedByPaidAt(),
                write.now());
        for (String bundleId : write.manifest().bundleIds()) {
            manifests.insertBundle(write.caseId(), bundleId);
        }
        // The event carries its own id and the revision it belongs to: deriving either from the
        // sequence number would make it change meaning when the case gains revisions.
        cases.insertTimeline(
                write.caseId(),
                UUID.randomUUID().toString(),
                1,
                TimelineEventType.CASE_CREATED.name(),
                openedDetail(write),
                write.now(),
                1);

        CaseCreatedResponse body = new CaseCreatedResponse(write.caseId(), CaseStatus.QUEUED, 1, 1L);
        String responseBody = mapper.writeValueAsString(body);
        cases.insertIdempotency(
                write.merchantId(),
                write.idempotencyKey(),
                write.requestHash(),
                201,
                responseBody,
                write.caseId(),
                write.now());
        return new CaseService.Created(body, false);
    }

    /**
     * The first trajectory entry, with the request's own words and no model's.
     *
     * <p>The customer's description is stored as they wrote it: the trajectory separates what was
     * reported from what was concluded (docs/agent-spec.md), and this entry is entirely the former.
     */
    private String openedDetail(CaseWrite write) {
        ObjectNode detail = mapper.createObjectNode();
        detail.put("line_id", write.lineId());
        detail.put("description", write.description());
        detail.putArray("requested_actions")
                .addAll(write.actions().stream()
                        .map(action -> mapper.getNodeFactory().stringNode(action.name()))
                        .toList());
        return CanonicalJson.canonicalize(detail);
    }
}
