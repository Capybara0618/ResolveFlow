package com.resolveflow.caseservice.casefile;

import com.resolveflow.caseservice.policy.PolicyManifestRepository;
import java.time.Duration;
import java.time.Instant;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.UUID;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.stereotype.Component;

/**
 * C06.1c: hand each case revision's run to the Agent, durably.
 *
 * <p>The shape is the outbox shape this service already uses for events, and the reason is the same: the
 * binding row is written by the transaction that opened the case, so it exists before anything goes over
 * the network (docs/domain-model.md:45). The dispatch is a separate, retryable consequence of that row, and
 * it is deliberately <em>not</em> called from inside the case transaction — a network call there would hold
 * a database transaction open across an HTTP request (docs/engineering.md:68).
 *
 * <p>One binding's failure never stops the pass. A batch that died on its first unreachable run would stop
 * dispatching every case behind it, which is the single failure mode a dispatch loop must not have.
 *
 * <p>The run id is <b>re-derived</b> from the binding rather than read out of it, and the two are asserted
 * to agree. Deriving it means a lost binding cannot cause a second run for one revision; checking it means a
 * binding that disagrees with the derivation is a loud failure instead of a run nobody can find.
 */
@Component
public class AgentRunDispatch {

    private static final Logger LOG = LoggerFactory.getLogger(AgentRunDispatch.class);

    /** The control-plane window a dispatched run is given (docs/agent-spec.md:42 — 控制面 deadline 默认 10 分钟). */
    private static final Duration DISPATCH_WINDOW = Duration.ofMinutes(10);

    /** What one pass did. */
    public record Pass(int dispatched, int failed, int skipped) {}

    private final AgentRunBindingRepository bindings;
    private final CaseRepository cases;
    private final PolicyManifestRepository manifests;
    private final EvidenceRepository evidence;
    private final AgentRunClient client;

    public AgentRunDispatch(
            AgentRunBindingRepository bindings,
            CaseRepository cases,
            PolicyManifestRepository manifests,
            EvidenceRepository evidence,
            AgentRunClient client) {
        this.bindings = bindings;
        this.cases = cases;
        this.manifests = manifests;
        this.evidence = evidence;
        this.client = client;
    }

    /**
     * One pass over the bindings the Agent has not accepted yet, oldest first.
     *
     * <p>Returns what happened rather than logging only, so a test (and a manual run of a backlog) can see
     * the outcome without reading a log file.
     */
    public Pass dispatchDue(int limit) {
        int dispatched = 0;
        int failed = 0;
        int skipped = 0;
        for (AgentRunBindingRepository.Binding binding : bindings.findPending(limit)) {
            try {
                if (dispatchOne(binding)) {
                    dispatched++;
                } else {
                    skipped++;
                }
            } catch (AgentRunClient.AgentRunRejectedException refused) {
                // The Agent answered "no" rather than "not now": the token or the body is wrong, and the
                // same request will be just as wrong next time. Logged loudly because this is a
                // configuration or coding fault, not an outage, and left PENDING so it stays visible
                // (a row silently marked delivered would hide a case that never starts).
                failed++;
                LOG.error(
                        "the Agent refused run {} for case {} revision {}: {}",
                        binding.runId(),
                        binding.caseId(),
                        binding.inputRevision(),
                        refused.getMessage());
            } catch (AgentRunClient.AgentUnavailableException unavailable) {
                // An outage. The binding stays PENDING and the next pass tries again; nothing is rolled back
                // and nothing is dropped, which is the whole reason the binding is a row.
                failed++;
                LOG.warn(
                        "run {} for case {} revision {} was not accepted yet; the next pass will retry: {}",
                        binding.runId(),
                        binding.caseId(),
                        binding.inputRevision(),
                        unavailable.getMessage());
            } catch (RuntimeException unexpected) {
                // Anything else is this service's own bug. It is counted and left for the next pass rather
                // than stopping the ones behind it.
                failed++;
                LOG.warn(
                        "dispatching run {} for case {} failed; the next pass will try again",
                        binding.runId(),
                        binding.caseId(),
                        unexpected);
            }
        }
        return new Pass(dispatched, failed, skipped);
    }

    /**
     * Try to hand one binding over. True when the Agent accepted it and the row was marked.
     *
     * <p>The mark happens only after the Agent answered, and only from PENDING: if another pass got there
     * first, this returns false and the run is not sent as a second attempt by this loop.
     */
    private boolean dispatchOne(AgentRunBindingRepository.Binding binding) {
        CaseRow row = cases.findCase(binding.caseId());
        if (row == null) {
            // The foreign key makes this impossible unless the case was deleted. Counted as skipped and
            // named, rather than sent with invented fields.
            LOG.warn("binding {} names case {} which does not exist", binding.runId(), binding.caseId());
            return false;
        }
        if (row.inputRevision() != binding.inputRevision()) {
            // The case has moved on. Dispatching the old revision is still correct — it is a run for that
            // revision, and the Agent's callback for it will come back STALE if the case no longer accepts
            // it (contracts/core/openapi-case.yaml:1284) — so this is not an error, only worth naming.
            LOG.info(
                    "dispatching run for case {} revision {} while the case is at revision {}",
                    binding.caseId(),
                    binding.inputRevision(),
                    row.inputRevision());
        }
        String derived = AgentRunId.forRevision(binding.caseId(), binding.inputRevision());
        if (!derived.equals(binding.runId())) {
            throw new IllegalStateException("binding " + binding.runId() + " disagrees with the derived run id "
                    + derived + " for case " + binding.caseId() + " revision " + binding.inputRevision());
        }
        Map<String, Object> body = runRequest(row, binding);
        String token = client.mintDispatchToken(row.merchantId(), row.customerId());
        client.dispatch(token, body);
        int marked = bindings.markDispatched(binding.caseId(), binding.inputRevision(), Instant.now());
        if (marked == 0) {
            LOG.info("run {} was accepted by the Agent but another pass had already marked it", binding.runId());
            return false;
        }
        return true;
    }

    /**
     * The run, in exactly the shape the Agent's contract declares.
     *
     * <p>Assembled here, in one place, so the wire shape can be asserted against the Python side rather than
     * discovered. Every member is a fact Case owns: the subjects come from the case row (never from a
     * request), the manifest is the one the case was pinned to, and the deadline is the submission plus the
     * control-plane window.
     */
    Map<String, Object> runRequest(CaseRow row, AgentRunBindingRepository.Binding binding) {
        PolicyManifestRepository.StoredManifest manifest = manifests.findManifest(row.caseId());
        if (manifest == null) {
            throw new IllegalStateException("case " + row.caseId() + " has no policy manifest to dispatch");
        }
        List<String> bundleIds = manifests.findBundleIds(row.caseId());
        if (bundleIds.isEmpty()) {
            throw new IllegalStateException("case " + row.caseId() + " has a manifest with no bundles");
        }
        List<String> actions = cases.findRequestedActions(row.caseId());

        Map<String, Object> context = new LinkedHashMap<>();
        context.put("merchant_id", row.merchantId());
        context.put("customer_id", row.customerId());
        context.put("order_id", row.orderId());
        context.put("line_id", row.lineId());

        Map<String, Object> request = new LinkedHashMap<>();
        request.put("description", row.description() == null ? "" : row.description());
        request.put("requested_actions", List.copyOf(actions));
        // A later revision carries the ids of material that existed by that revision. The Agent reads the
        // authoritative records through the scoped tool; ids here are routing hints, not trusted content.
        request.put(
                "evidence_refs",
                List.copyOf(evidence.findIdsAtRevision(
                        row.caseId(), binding.inputRevision(), CaseEvidenceService.MAX_RECORDS)));

        Map<String, Object> policy = new LinkedHashMap<>();
        // The merchant is dispatched with the manifest because it is what the run filters retrieval by
        // (C07.1). It is read from the pin rather than from the case row: the run has to be able to check
        // "the bundle I retrieved belongs to my merchant" against the same record it was opened under.
        policy.put("merchant_id", manifest.merchantId());
        policy.put("bundle_ids", List.copyOf(bundleIds));
        policy.put("manifest_hash", manifest.manifestHash());
        policy.put("safety_epoch", manifest.safetyEpoch());

        Map<String, Object> body = new LinkedHashMap<>();
        body.put("run_id", binding.runId());
        body.put("case_id", row.caseId());
        body.put("input_revision", binding.inputRevision());
        body.put("context", context);
        body.put("request", request);
        body.put("policy_manifest", policy);
        // Each revision gets its own control-plane window. Reusing case.created_at would make a fresh run
        // on an older case expire before the Agent accepted it.
        body.put("deadline_at", binding.createdAt().plus(DISPATCH_WINDOW).toString());
        // A fresh trace id per dispatch, in the contract's own format. The Agent carries it into its logs,
        // and it is the only correlation available until this service reports spans of its own.
        body.put(
                "traceparent",
                "00-" + UUID.randomUUID().toString().replace("-", "") + "-"
                        + UUID.randomUUID().toString().replace("-", "").substring(0, 16) + "-01");
        return body;
    }
}
