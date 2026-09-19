package com.resolveflow.caseservice.casefile;

import com.resolveflow.shared.contract.CanonicalJson;
import java.time.Instant;
import org.springframework.stereotype.Service;
import tools.jackson.databind.JsonNode;
import tools.jackson.databind.ObjectMapper;

/**
 * Accepting a proposal: re-check it, then record it with the outcome.
 *
 * <p>Two calls rather than one, and the split is the writer's ordering rule: the check only reads, so it
 * happens before the delivery is claimed, and the insert happens after the claim. A redelivery that loses
 * the race on the callback id therefore rolls back with nothing written, instead of leaving a proposal
 * behind from a delivery that was refused.
 *
 * <p>The document stored is the one that arrived (canonicalised, but member for member what the run sent),
 * not a copy rebuilt from the parsed record. The contract says an absent amount is not a null one, so
 * re-serialising a record would turn "nothing was suggested" into an explicit null the schema forbids —
 * and a stored proposal that no longer matches what was submitted is not evidence of anything.
 */
@Service
public class ProposalService {

    /** What was written: the outcome a reviewer sees, and where it sits in the case's proposal history. */
    public record Recorded(ProposalStatus status, Long recomputedAmountMinor, String refusalReason, long sequence) {}

    private final ProposalRepository proposals;
    private final ProposalReCheck reCheck;
    private final ObjectMapper mapper;

    public ProposalService(ProposalRepository proposals, ProposalReCheck reCheck, ObjectMapper mapper) {
        this.proposals = proposals;
        this.reCheck = reCheck;
        this.mapper = mapper;
    }

    /** Read-only: decides VALIDATED or REJECTED, or throws when the message is not a proposal at all. */
    public ProposalReCheck.Outcome check(CaseRow row, ProposalSubmission submission) {
        return reCheck.check(row, submission);
    }

    /**
     * Store the proposal and its outcome, in the caller's transaction (the callback writer's).
     *
     * <p>{@code document} is the payload as received; {@code payloadHash} is the delivery's own hash of that
     * callback, so the row can be tied back to the delivery that produced it.
     */
    public Recorded record(
            CaseRow row,
            ProposalSubmission submission,
            JsonNode document,
            String payloadHash,
            ProposalReCheck.Outcome outcome,
            Instant now) {
        long sequence = proposals.nextSequence(row.caseId());
        proposals.insert(
                submission.proposalId(),
                row.caseId(),
                submission.runId(),
                submission.inputRevision(),
                sequence,
                outcome.status().name(),
                outcome.recomputedAmountMinor(),
                outcome.refusalReason(),
                CanonicalJson.canonicalize(document),
                payloadHash,
                now);
        return new Recorded(outcome.status(), outcome.recomputedAmountMinor(), outcome.refusalReason(), sequence);
    }

    /**
     * The proposal a reader of this case should see, as the contract's {@code ProposalView}.
     *
     * <p>The submitted members are echoed exactly as they were stored and the case-side members are added
     * beside them: the status this service decided (STALE when the case has moved past the revision it was
     * about), what it recomputed, and why it refused. A reviewer comparing the run's suggestion with the
     * recomputed amount sees both, which is the point of keeping the suggestion at all.
     */
    public JsonNode view(String caseId, int caseInputRevision) {
        ProposalRepository.StoredProposal stored = proposals.findLatest(caseId);
        if (stored == null) {
            return null;
        }
        var view = mapper.createObjectNode();
        stored.payloadAsJson(mapper).properties().forEach(entry -> view.set(entry.getKey(), entry.getValue()));
        view.put("status", stored.statusAt(caseInputRevision).name());
        if (stored.recomputedAmountMinor() != null) {
            view.put("recomputed_amount_minor", stored.recomputedAmountMinor());
        }
        if (stored.refusalReason() != null) {
            view.put("refusal_reason", stored.refusalReason());
        }
        view.put("created_at", stored.createdAt().toString());
        return view;
    }
}
