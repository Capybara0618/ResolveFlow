package com.resolveflow.caseservice.casefile;

import java.time.Instant;
import java.util.UUID;
import org.springframework.stereotype.Service;
import tools.jackson.databind.ObjectMapper;

/**
 * Creating the authorisation a human decides on, and reading it back (C03.3a).
 *
 * <p>Called from the callback writer, inside the transaction that already holds the case's row lock, so
 * "the proposal was validated" and "there is something to approve" become true together or not at all
 * (docs/core-contracts.md:67). The one thing that fixes everything else is the operation id: it is drawn
 * here, before anyone has decided, because the hashed payload has to be settled before approval
 * (docs/core-contracts.md:19). An operation id drawn at execution time would make the payload depend on who
 * approved and when, and a retry could not reuse it.
 *
 * <p>The payload hash is stored, not recomputed on read. {@code payload_hash} covers the twelve command
 * fields, and the row holds every one of them plus the case row's line and merchant, so the value can still
 * be re-derived and compared (C04's consumption does exactly that) — but what a human approves has to be the
 * value that was fixed at creation, not one recomputed from columns that may have moved since.
 *
 * <p>Only a validated, money-moving proposal gets an authorisation. A refused proposal has nothing to
 * approve, and a validated recommendation that does not move money has nothing this service could execute:
 * creating a row for either would put a decision in front of a reviewer that no approval could carry out.
 */
@Service
public class AuthorizationService {

    /** What was created, for the trajectory and for the writer's receipt. */
    public record Created(
            String authorizationId,
            long authorizationVersion,
            String plannedOperationId,
            long amountMinor,
            String payloadHash) {}

    private final AuthorizationRepository authorizations;
    private final ObjectMapper mapper;

    public AuthorizationService(AuthorizationRepository authorizations, ObjectMapper mapper) {
        this.authorizations = authorizations;
        this.mapper = mapper;
    }

    /**
     * Fix the payload for a validated refund and record who would have to approve it.
     *
     * @return what was created, or {@code null} when this outcome authorised nothing
     */
    public Created create(CaseRow row, ProposalReCheck.Outcome outcome, String proposalId, Instant now) {
        if (!outcome.isExecutable()) {
            return null;
        }
        String authorizationId = UUID.randomUUID().toString();
        String operationId = UUID.randomUUID().toString();
        RefundCommand command = new RefundCommand(
                operationId,
                row.caseId(),
                authorizationId,
                row.inputRevision(),
                row.lineId(),
                row.merchantId(),
                ExecutableAction.REFUND,
                outcome.execution().quantity(),
                outcome.execution().currency(),
                outcome.recomputedAmountMinor(),
                outcome.execution().policyVersion());
        String payloadHash = command.payloadHash(mapper);
        authorizations.insert(
                authorizationId,
                row.caseId(),
                1L,
                AuthorizationStatus.PENDING_REVIEW.name(),
                ExecutableAction.REFUND.wire(),
                row.inputRevision(),
                proposalId,
                operationId,
                payloadHash,
                outcome.recomputedAmountMinor(),
                outcome.execution().quantity(),
                outcome.execution().currency(),
                outcome.execution().policyVersion(),
                null,
                now,
                now);
        return new Created(authorizationId, 1L, operationId, outcome.recomputedAmountMinor(), payloadHash);
    }

    /** The authorisation a reader of this case should see, or {@code null} when there is none yet. */
    public AuthorizationStateResponse view(String caseId) {
        AuthorizationRepository.StoredAuthorization stored = authorizations.findLatest(caseId);
        return stored == null ? null : AuthorizationStateResponse.of(stored);
    }
}
