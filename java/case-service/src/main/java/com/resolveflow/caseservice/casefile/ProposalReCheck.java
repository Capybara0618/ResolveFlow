package com.resolveflow.caseservice.casefile;

import com.resolveflow.caseservice.order.CommerceOrderLineClient;
import com.resolveflow.caseservice.policy.PolicyManifestRepository;
import com.resolveflow.caseservice.policy.PolicyRepository;
import java.util.HashSet;
import java.util.List;
import java.util.Set;
import org.springframework.stereotype.Component;

/**
 * The re-check a proposal has to survive before it means anything (docs/product-spec.md:25).
 *
 * <p>The split this class implements, and the reason the two halves answer differently:
 *
 * <ul>
 *   <li><b>Structure and binding are 422s.</b> A wrong protocol version, an unknown action, a
 *       {@code case_id} that disagrees with the delivery, an amount on a non-refund — these are the
 *       producer's mistake in the message it sent, so the answer is "this message is not a proposal"
 *       (docs/core-contracts.md:9 requires the body to agree with the JWT and the case binding).
 *   <li><b>Content is a stored REJECTED.</b> A citation that does not resolve, a line with nothing left to
 *       refund, a suggestion larger than the line can pay — these are a <em>proposal that was checked and
 *       refused</em>. That is a durable fact about this case, so it is recorded with its reason and shown to
 *       the reviewer rather than thrown away as a protocol error.
 * </ul>
 *
 * <p>Nothing here trusts the run: the citations are resolved against the version pinned on this case and
 * re-hashed from the stored rule text, and the amount is recomputed from Commerce's own line amounts. The
 * run's {@code suggested_amount_minor} is kept so the disagreement is visible, never used.
 */
@Component
public class ProposalReCheck {

    /** What the re-check decided, and why when it refused. */
    public record Outcome(
            ProposalStatus status,
            Long recomputedAmountMinor,
            String refusalReason,
            RefusalKind refusalKind,
            Executable execution) {

        /**
         * Which kind of refusal this is, because the two answer a caller differently.
         *
         * <p>{@code CITATION} is a fault in the submission itself — a citation this service cannot verify, or a
         * claim about the money that does not survive recomputation. {@code WORLD} is this service's own state
         * saying no: no policy pinned on the case, the line gone or no longer this case's, nothing left to
         * refund. A caller that is still connected (the human route, C03.3c) gets 422 for the first and 409
         * for the second; a stored refusal records the reason either way, because what a reviewer needs is the
         * reason.
         */
        public enum RefusalKind {
            CITATION,
            WORLD
        }

        /**
         * The rest of the execution payload a validated refund fixes (C03.3a).
         *
         * <p>The amount is not repeated here: it is {@code recomputedAmountMinor}, the number this check
         * arrived at from Commerce's own line amounts, and a second field holding the same value would be a
         * second thing to keep in step. What is here is what the check read on the way and would otherwise
         * have to read again: the line's quantity and currency, and the version of the policy the proposal
         * relies on. A command carries exactly one {@code policy_version}, so it is the version behind the
         * proposal's first citation - the policy this refund actually leans on - rather than a guess over
         * the pinned set.
         */
        public record Executable(int quantity, String currency, String policyVersion) {}

        public boolean isValidated() {
            return status == ProposalStatus.VALIDATED;
        }

        /** Whether this outcome gave the case something a human can approve and this service can execute. */
        public boolean isExecutable() {
            return isValidated() && execution != null;
        }

        static Outcome validated(Long recomputedAmountMinor) {
            return new Outcome(ProposalStatus.VALIDATED, recomputedAmountMinor, null, null, null);
        }

        static Outcome executable(long recomputedAmountMinor, Executable execution) {
            return new Outcome(ProposalStatus.VALIDATED, recomputedAmountMinor, null, null, execution);
        }

        static Outcome refused(RefusalKind kind, String reason) {
            return new Outcome(ProposalStatus.REJECTED, null, reason, kind, null);
        }
    }

    private final PolicyRepository policies;
    private final PolicyManifestRepository manifests;
    private final CommerceOrderLineClient commerce;

    public ProposalReCheck(
            PolicyRepository policies, PolicyManifestRepository manifests, CommerceOrderLineClient commerce) {
        this.policies = policies;
        this.manifests = manifests;
        this.commerce = commerce;
    }

    /**
     * Check one submission against this case and this service's own records.
     *
     * @throws CaseService.SemanticInvalidException when the message itself is not a valid proposal
     */
    public Outcome check(CaseRow row, ProposalSubmission submission) {
        requireStructure(submission);

        if (!submission.caseId().equals(row.caseId())) {
            throw new CaseService.SemanticInvalidException("case_id in the proposal (" + submission.caseId()
                    + ") is not the case it was delivered for (" + row.caseId() + ")");
        }
        if (submission.inputRevision() != row.inputRevision()) {
            throw new CaseService.SemanticInvalidException("input_revision in the proposal is "
                    + submission.inputRevision() + " but this case is at revision " + row.inputRevision());
        }
        return checkContent(
                row, submission.policies(), submission.recommendedAction(), submission.suggestedAmountMinor());
    }

    /**
     * The half of the check that is not about who wrote the proposal (C03.3c-1).
     *
     * <p>A person's proposal is checked by exactly this code, because the question is the same one: do the
     * citations resolve against the version pinned on this case, and does the line still owe what the
     * proposal would pay? Splitting it out rather than reimplementing it is what keeps "a human proposal is
     * verified too" from being a promise about a second implementation.
     *
     * @param suggestedAmountMinor the run's suggestion, or {@code null} for a caller that supplied no amount
     *     (a human proposal has no amount member: the money is recomputed, never asserted)
     */
    public Outcome checkContent(
            CaseRow row, List<PolicyCitation> citedPolicies, String action, Long suggestedAmountMinor) {
        List<String> pinned = manifests.findBundleIds(row.caseId());
        if (pinned.isEmpty()) {
            return Outcome.refused(
                    Outcome.RefusalKind.WORLD,
                    "this case has no pinned policy version, so none of its citations can be"
                            + " checked against the version that was in force when it was opened");
        }
        for (PolicyCitation citation : citedPolicies) {
            String problem = citationProblem(pinned, citation);
            if (problem != null) {
                return Outcome.refused(Outcome.RefusalKind.CITATION, problem);
            }
        }
        if (RecommendedAction.of(action).movesMoney() && citedPolicies.isEmpty()) {
            return Outcome.refused(
                    Outcome.RefusalKind.CITATION,
                    "a refund proposal has to cite the policy it relies on; without a citation"
                            + " there is nothing this service can check except the amount");
        }

        RecommendedAction recommended = RecommendedAction.of(action);
        if (!recommended.movesMoney()) {
            // No amount is computed for an action that does not move money, and no amount is invented.
            return Outcome.validated(null);
        }

        var context = commerce.readLineContext(row.lineId());
        if (context.isEmpty()) {
            return Outcome.refused(
                    Outcome.RefusalKind.WORLD,
                    "Commerce no longer has line " + row.lineId() + ", so the amount that"
                            + " would be refunded cannot be read from the record it would be paid from");
        }
        var line = context.get();
        if (!row.merchantId().equals(line.merchantId()) || !row.customerId().equals(line.customerId())) {
            // The context is the one unscoped line read (C03.2a), so this is where its ownership is confirmed.
            return Outcome.refused(
                    Outcome.RefusalKind.WORLD,
                    "line " + row.lineId() + " belongs to another merchant or customer, so it is"
                            + " not this case's line to refund");
        }
        long refundable = line.refundableAmountMinor();
        if (refundable <= 0) {
            return Outcome.refused(
                    Outcome.RefusalKind.WORLD,
                    "line " + row.lineId() + " has nothing left to refund: the order's ledger"
                            + " already accounts for its paid amount in full");
        }
        if (suggestedAmountMinor != null && suggestedAmountMinor > refundable) {
            return Outcome.refused(
                    Outcome.RefusalKind.CITATION,
                    "the run suggested " + suggestedAmountMinor + " minor units but this service recomputed "
                            + refundable + " from the line's paid, refunded and reserved amounts");
        }
        // The version is read from the bundle behind the proposal's first citation, which the loop above has
        // already proved exists and is pinned on this case.
        PolicyRepository.StoredBundle cited =
                policies.findBundle(citedPolicies.get(0).bundleId());
        return Outcome.executable(
                refundable, new Outcome.Executable(line.quantity(), line.currency(), cited.version()));
    }

    /**
     * The shape an evidence reference has to have, whoever wrote it (C03.3c-1).
     *
     * <p>Shared by both paths because the rule is not about the author: a reference is a fixed mapping this
     * service looks up ({@code kind:rest}), and a URL is refused rather than fetched, so that a citation can
     * never become a way to make this service read something the submitter chose.
     *
     * <p>What is <em>not</em> checked here is whether the referenced material exists or says what the
     * proposal claims: refs are recorded, not verified, until C04 binds them to the records this service
     * issued. That gap is stated rather than papered over.
     */
    public void requireEvidenceRefs(List<EvidenceCitation> evidence, int minItems, int maxItems) {
        if (evidence == null || evidence.size() < minItems || evidence.size() > maxItems) {
            throw new CaseService.SemanticInvalidException(
                    "evidence_refs must hold between " + minItems + " and " + maxItems + " references");
        }
        for (EvidenceCitation citation : evidence) {
            if (citation.sourceRef() == null || !citation.sourceRef().matches("^(?!https?://)[a-z][a-z0-9_]*:\\S+$")) {
                throw new CaseService.SemanticInvalidException("evidence source_ref is not a controlled reference: "
                        + citation.sourceRef() + " (a URL is refused, not fetched)");
            }
        }
    }

    /** Why one citation cannot be trusted, or {@code null} if it can.
     *
     * <p>The hash is recomputed from the stored rule and compared with the cited one (C03.2b-2a), so a
     * citation of a rule whose text has since changed fails here instead of matching a stale hash. The bundle
     * has to be one of the versions pinned on the case: citing a newer policy for an older payment is exactly
     * the mistake pinning exists to prevent (C03.1b).
     */
    private String citationProblem(List<String> pinned, PolicyCitation citation) {
        if (!pinned.contains(citation.bundleId())) {
            return "the proposal cites policy " + citation.bundleId() + ", which is not the version pinned on"
                    + " this case (" + String.join(", ", pinned) + ")";
        }
        PolicyRepository.StoredBundle bundle = policies.findBundle(citation.bundleId());
        if (bundle == null) {
            return "the proposal cites policy " + citation.bundleId() + ", which this service does not have";
        }
        if (!bundle.version().equals(citation.version())) {
            return "the proposal cites " + citation.bundleId() + " version " + citation.version()
                    + " but the stored version is " + bundle.version();
        }
        for (var rule : policies.findRules(citation.bundleId())) {
            if (!rule.ruleId().equals(citation.ruleId()) || !rule.chunkId().equals(citation.chunkId())) {
                continue;
            }
            if (!rule.contentHash().equals(citation.contentHash())) {
                return "the proposal cites " + citation.bundleId() + "/" + citation.chunkId()
                        + " with content hash " + citation.contentHash() + " but the stored rule hashes to "
                        + rule.contentHash();
            }
            return null;
        }
        return "the proposal cites rule " + citation.ruleId() + " (" + citation.chunkId() + ") which is not in "
                + citation.bundleId();
    }

    private void requireStructure(ProposalSubmission submission) {
        if (submission.schemaVersion() != ProposalSubmission.SCHEMA_VERSION) {
            throw new CaseService.SemanticInvalidException("a core proposal is schema_version "
                    + ProposalSubmission.SCHEMA_VERSION + ", not " + submission.schemaVersion());
        }
        requireUuid("proposal_id", submission.proposalId());
        requireUuid("run_id", submission.runId());
        requireUuid("case_id", submission.caseId());
        CaseType.of(submission.caseType());
        RecommendedAction.of(submission.recommendedAction());
        if (submission.summary() == null
                || submission.summary().isBlank()
                || submission.summary().length() > 2000) {
            throw new CaseService.SemanticInvalidException("summary is required and at most 2000 characters");
        }
        List<String> reasons = submission.reasonCodes();
        if (reasons == null || reasons.isEmpty() || reasons.size() > 16) {
            throw new CaseService.SemanticInvalidException("reason_codes must hold between 1 and 16 codes");
        }
        Set<String> seen = new HashSet<>();
        for (String code : reasons) {
            if (code == null || !code.matches("^[A-Z][A-Z0-9_]{1,63}$")) {
                throw new CaseService.SemanticInvalidException("reason code is not a contract reason code: " + code);
            }
            if (!seen.add(code)) {
                throw new CaseService.SemanticInvalidException("reason code appears twice: " + code);
            }
        }
        requireEvidenceRefs(submission.evidence(), 0, ProposalSubmission.MAX_CITATIONS);
        if (submission.policies().size() > 10) {
            throw new CaseService.SemanticInvalidException("at most 10 policy references, found "
                    + submission.policies().size());
        }
        if (submission.suggestedAmountMinor() != null) {
            if (submission.suggestedAmountMinor() < 0 || submission.suggestedAmountMinor() > 1_000_000_000L) {
                throw new CaseService.SemanticInvalidException(
                        "suggested_amount_minor is outside the contract's range: " + submission.suggestedAmountMinor());
            }
            if (!RecommendedAction.of(submission.recommendedAction()).movesMoney()) {
                throw new CaseService.SemanticInvalidException(
                        "an amount belongs to a REFUND proposal, not to " + submission.recommendedAction());
            }
        }
        List<String> missing = submission.missingEvidence();
        if (missing != null) {
            if (missing.size() > 10) {
                throw new CaseService.SemanticInvalidException(
                        "at most 10 missing-evidence entries, found " + missing.size());
            }
            for (String entry : missing) {
                if (entry == null || entry.isBlank() || entry.length() > 200) {
                    throw new CaseService.SemanticInvalidException("a missing-evidence entry is 1..200 characters");
                }
            }
        }
    }

    private static void requireUuid(String member, String value) {
        if (value == null
                || !value.matches("^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")) {
            throw new CaseService.SemanticInvalidException(member + " must be a UUID, got " + value);
        }
    }
}
