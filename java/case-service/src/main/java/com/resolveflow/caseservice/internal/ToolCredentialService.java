package com.resolveflow.caseservice.internal;

import com.resolveflow.caseservice.casefile.AgentRunBindingRepository;
import com.resolveflow.caseservice.casefile.CaseRepository;
import com.resolveflow.caseservice.casefile.CaseRow;
import com.resolveflow.shared.security.JwtCodec;
import com.resolveflow.shared.security.ServiceScopes;
import java.time.Duration;
import java.time.Instant;
import java.util.List;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Service;

/**
 * C06.4④: mint the scoped credential a run's tools authenticate with, or refuse to.
 *
 * <p>The route existed in {@code contracts/core/openapi-case.yaml} (C00) with no implementation, while the five
 * tools presented a token read out of {@code RESOLVEFLOW_TOOL_SERVICE_TOKEN}. Those are not the same credential
 * and the difference is the whole point of this class:
 *
 * <ul>
 *   <li>a deployment-wide token is not bound to a run, so it cannot be refused when the run stops being the run
 *       that describes the case, and it cannot carry the line it is allowed to read;
 *   <li>{@code docs/core-contracts.md:74} requires the credential to be bound to
 *       run/case/revision/merchant/customer/line/aud/scope, and each of those has to come from a record this
 *       service owns rather than from the caller's body;
 *   <li>the contract's own description says a renewal is issued <em>only after case-service confirms the revision
 *       is still valid</em> — which is why this is a service and not a pure signing function.
 * </ul>
 *
 * <p><b>Where the run context comes from.</b> {@code merchant_id}, {@code buyer_id} and {@code line_id} are
 * read from the case row, never from the request: the body carries only {@code case_id} and
 * {@code input_revision} (the contract declares nothing else), and a credential that echoed a caller's idea of
 * the merchant would be a credential the caller scoped. The {@code case_id} in the body is still checked against
 * the run binding, because the run id in the path and the case in the body are two statements about one run and
 * they can disagree.
 *
 * <p><b>Why the revision must be current.</b> The binding row is the durable record that a run was opened for a
 * revision, and it survives the case moving on — deliberately, because the run's callback for that revision is
 * still a real callback and Case answers it STALE rather than pretending it never happened. A credential is a
 * different question: it is authority to read the <em>current</em> material, so a run whose revision is no longer
 * current gets a 409 rather than a fresh token. Handing one out would let a superseded run keep reading the case
 * it no longer describes.
 */
@Service
public class ToolCredentialService {

    /**
     * The revision a credential was asked for is not the case's current one.
     *
     * <p>409 rather than 404: the run exists and the binding is real, so answering "not found" would make a
     * superseded run indistinguishable from one that was never dispatched — and the two need different
     * responses from whoever is looking.
     */
    public static class RevisionNotCurrentException extends RuntimeException {

        private static final long serialVersionUID = 1L;

        public RevisionNotCurrentException(String message) {
            super(message);
        }
    }

    /**
     * The run in the path does not exist, or names no revision of the case the body gave.
     *
     * <p>A 404, which the contract declares for this route. The three ways to reach it are one answer on purpose:
     * an unknown run id, an unknown case, and a case with no run at that revision are all "there is no such run
     * here", and telling them apart to a caller would disclose which case ids exist — the same rule the public
     * case reads follow (docs/core-contracts.md:27).
     */
    public static class RunNotFoundException extends RuntimeException {

        private static final long serialVersionUID = 1L;

        public RunNotFoundException(String message) {
            super(message);
        }
    }

    /**
     * The body and the path name different runs.
     *
     * <p>422 rather than 404: both may exist and the request is still not about one run. This is the same refusal
     * the run intake makes when the body disagrees with the token (docs/core-contracts.md:60 — body 主体必须与
     * service JWT 及 Case 绑定一致), and the same reading of {@code SemanticInvalid}: the message is not a
     * credential request because its two halves describe different things. Answering with a credential either way
     * would mint a token for whichever half the reader trusted, and the two halves name different lines.
     */
    public static class RunMismatchException extends RuntimeException {

        private static final long serialVersionUID = 1L;

        public RunMismatchException(String message) {
            super(message);
        }
    }

    /**
     * The scopes a tool credential carries. Fixed here rather than accepted from the caller.
     *
     * <p>{@code commerce:read} and {@code policy:read} are the contract's own example for this route
     * ({@code contracts/core/openapi-case.yaml:846}), and they cover exactly what the five whitelisted tools do:
     * read Commerce's order, shipment and refund state, and read the case's material and pinned policy. There is
     * deliberately no write scope — the Agent has no write tools at all ({@code docs/core-scope.md}), so a scope
     * that could authorize one would be a permission nothing should be able to ask for.
     *
     * <p>A caller cannot pass scopes in, which is what {@code docs/core-contracts.md:74} means by "Agent 不能自行
     * 扩大 scope": the set is a property of the route, not of the request.
     *
     * <p>The values come from {@link com.resolveflow.shared.security.ServiceScopes} — the same constants the
     * services' own filters require. These were literals here until AS02.3's security sub-step made the claim
     * enforceable, at which point a mint that spelled them itself could have drifted from the routes checking them
     * without either side failing to compile.
     */
    public static final List<String> TOOL_SCOPES = ServiceScopes.TOOL_CREDENTIAL;

    /** The service name the credential names as its subject. */
    private static final String TOOL_SUBJECT = "agent-service";

    private final AgentRunBindingRepository bindings;
    private final CaseRepository cases;
    private final JwtCodec codec;
    private final Duration timeToLive;

    public ToolCredentialService(
            AgentRunBindingRepository bindings,
            CaseRepository cases,
            JwtCodec codec,
            @Value("${resolveflow.tool-credential.ttl:PT5M}") Duration timeToLive) {
        this.bindings = bindings;
        this.cases = cases;
        this.codec = codec;
        this.timeToLive = timeToLive;
    }

    /**
     * The credential for one run, or the refusal that says why not.
     *
     * <p>Read-only: nothing is written, so a renewal cannot change the case and cannot be the thing that makes a
     * run current. That is worth stating because the obvious alternative — record on the binding that a
     * credential was issued — would make this route a write path reached by a service that is only asking a
     * question.
     *
     * <p><b>The order of the four checks is the design</b>, and it was got wrong first: a version that asked
     * "is this the run for this case at this revision" before looking the run up by id alone answered 404 to a
     * request whose body named a different case entirely, which reads as "your run does not exist" for a run the
     * caller can see. So:
     *
     * <ol>
     *   <li><b>Is the case real?</b> No: 404. Whether a case id exists is not disclosed to a caller that named it
     *       (docs/core-contracts.md:27).
     *   <li><b>Do the two halves name the same case?</b> The path's run is looked up <em>by run id</em>, so a run
     *       that exists for some other case is a 422 — the request describes two investigations, which is the
     *       same refusal the run intake makes when the body disagrees with the token
     *       (docs/core-contracts.md:60). This check has to come before the revision one, because the run in the
     *       path may name a revision this case never had.
     *   <li><b>Does this case have a run at the requested revision?</b> No: 404. The revision may have been
     *       skipped, or the run may never have been dispatched.
     *   <li><b>Is that revision still current?</b> No: 409. The run is real and the binding is real, so "not
     *       found" would make a superseded run indistinguishable from one that was never dispatched.
     * </ol>
     */
    public ToolCredentialResponse issue(String runId, String caseId, int inputRevision) {
        CaseRow row = cases.findCase(caseId);
        if (row == null) {
            throw new RunNotFoundException("no run " + runId + " for a case this service holds");
        }
        AgentRunBindingRepository.Binding named = bindings.findByRunId(runId);
        if (named == null) {
            throw new RunNotFoundException("no run " + runId + " for a case this service holds");
        }
        if (!named.caseId().equals(caseId)) {
            throw new RunMismatchException("run " + runId + " belongs to case " + named.caseId() + ", not to the case "
                    + caseId + " this request names in its body");
        }
        if (named.inputRevision() != inputRevision) {
            // The run is real but it is not the run for the revision the body asked about. Refused rather than
            // answered with a credential for a revision nobody requested.
            throw new RunNotFoundException("run " + runId + " is revision " + named.inputRevision() + " of case "
                    + caseId + ", not revision " + inputRevision);
        }
        if (row.inputRevision() != inputRevision) {
            throw new RevisionNotCurrentException("case " + caseId + " is at revision " + row.inputRevision() + ", not "
                    + inputRevision + "; a credential is authority to read the current material");
        }

        Instant now = Instant.now();
        JwtCodec.ToolCredential claims = new JwtCodec.ToolCredential(
                TOOL_SUBJECT,
                row.caseId(),
                named.runId(),
                inputRevision,
                row.merchantId(),
                row.buyerId(),
                row.lineId(),
                TOOL_SCOPES,
                timeToLive);
        String token = codec.issueToolCredential(claims, now);
        return new ToolCredentialResponse(token, now.plus(timeToLive), TOOL_SCOPES);
    }

    /**
     * The lifetime a credential is minted with ({@code docs/contracts.md:96}: 5分钟有效), injectable so a test
     * can shorten it without waiting five minutes.
     */
    public Duration timeToLive() {
        return timeToLive;
    }
}
