package com.resolveflow.caseservice.casefile;

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
 * Cancelling a case before its authorisation is consumed (docs/domain-model.md:55).
 *
 * <p>Cancellation is the first terminal transition the core has, so it is also the first place where the
 * line's active slot is released: a terminal case no longer occupies the line, which is what lets the same
 * line be asked about again (docs/domain-model.md:26). Committing the status and releasing the slot in one
 * transaction is the point — a case that is cancelled but still holding its slot would refuse every future
 * request about that line, and a released slot on a live case would allow two active cases at once.
 *
 * <p>It is not idempotent. A cancel that arrives after the case is already terminal is 409, because "this
 * transition is not available" is the truth and "cancelled" would be a claim about a cancellation that did
 * not happen. The guard is checked under the case's row lock and repeated in the UPDATE's WHERE clause, so
 * two cancels arriving together cannot both move the version.
 */
@Service
public class CaseCancellationService {

    private final CaseRepository cases;
    private final Clock clock;
    private final ObjectMapper mapper = new ObjectMapper();

    public CaseCancellationService(CaseRepository cases, Clock clock) {
        this.cases = cases;
        this.clock = clock;
    }

    @Transactional
    public CaseCancelResponse cancel(AuthenticatedPrincipal principal, String caseId, ReasonRequest request) {
        String reason = requireReason(request);

        CaseRow row = cases.findCaseForUpdate(caseId);
        if (row == null || !visibleTo(principal, row)) {
            throw new CaseReadService.CaseNotVisibleException();
        }
        requireCancellable(row);

        Instant now = Instant.now(clock);
        // The expected status is part of the UPDATE, so the transition is conditional in the database
        // rather than only in the check above it.
        if (cases.markCancelled(caseId, row.status().name(), now) != 1) {
            throw new CaseStateConflictException(
                    "this case is no longer in " + row.status() + "; nothing was cancelled");
        }
        cases.releaseActiveSlot(row.merchantId(), row.lineId());
        cases.insertTimeline(
                caseId,
                UUID.randomUUID().toString(),
                nextSequence(caseId),
                TimelineEventType.CASE_CLOSED.name(),
                closedDetail(reason, principal),
                now,
                row.inputRevision());

        return new CaseCancelResponse(caseId, CaseStatus.CANCELLED, row.version() + 1);
    }

    private static void requireCancellable(CaseRow row) {
        if (row.status().isTerminal()) {
            throw new CaseStateConflictException(
                    "this case already ended as " + row.status() + "; a terminal case has no further transition");
        }
        if (row.status() == CaseStatus.EXECUTING || row.status() == CaseStatus.RECONCILING) {
            throw new CaseStateConflictException(
                    "this case is already executing; there is no cancel edge after consumption");
        }
    }

    private static boolean visibleTo(AuthenticatedPrincipal principal, CaseRow row) {
        if (!row.merchantId().equals(principal.merchantId())) {
            return false;
        }
        return principal.role() != Role.CUSTOMER || row.customerId().equals(principal.customerId());
    }

    private static String requireReason(ReasonRequest request) {
        if (request == null || request.reason() == null || request.reason().isBlank()) {
            throw new CaseService.SemanticInvalidException("reason is required");
        }
        if (request.reason().length() > 500) {
            throw new CaseService.SemanticInvalidException("reason must be at most 500 characters");
        }
        return request.reason();
    }

    private String closedDetail(String reason, AuthenticatedPrincipal principal) {
        ObjectNode detail = mapper.createObjectNode();
        // The status is in the detail because CASE_CLOSED is the contract's only terminal event type; a
        // reader distinguishes "cancelled" from a future "rejected" by this field, not by a type the
        // contract does not have.
        detail.put("status", CaseStatus.CANCELLED.name());
        detail.put("reason", reason);
        detail.put("cancelled_by", principal.subject());
        detail.put("cancelled_role", principal.role().name());
        return com.resolveflow.shared.contract.CanonicalJson.canonicalize(detail);
    }

    private int nextSequence(String caseId) {
        Integer highest = cases.highestSequence(caseId);
        return highest == null ? 1 : highest + 1;
    }
}
