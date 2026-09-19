package com.resolveflow.caseservice.policy;

import com.fasterxml.jackson.annotation.JsonInclude;
import com.fasterxml.jackson.annotation.JsonProperty;
import java.util.List;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

/**
 * The authoritative policy text (docs/core-contracts.md:51).
 *
 * <p>This is the one internal route a run depends on: the Agent cites a rule, and Java re-checks the citation
 * against this text rather than against the Agent's summary. That is why the bundle is served from storage
 * with its hash, and why the response is pinned to the bundle_id the case recorded — a citation checked
 * against a *newer* policy would pass while being wrong.
 *
 * <p>Never reached by a user: the {@code /internal/**} filter refuses a user token before this method runs.
 */
@RestController
@RequestMapping("/internal/v1/policies")
public class PolicyController {

    private final PolicyRepository policies;

    public PolicyController(PolicyRepository policies) {
        this.policies = policies;
    }

    /** The contract's {@code PolicyBundle}: the stored version, its hash and its rules in source order. */
    @JsonInclude(JsonInclude.Include.NON_NULL)
    public record PolicyBundleResponse(
            @JsonProperty("bundle_id") String bundleId,
            String version,
            @JsonProperty("manifest_hash") String manifestHash,
            @JsonProperty("safety_epoch") Integer safetyEpoch,
            List<Rule> rules) {}

    /**
     * The contract's {@code PolicyRule}, named for the wire rather than reusing the stored record.
     *
     * <p>The first version of this route returned {@link PolicyRule} directly and serialised {@code ruleId}:
     * the domain record is named in camel case, and the wire is snake case. Reusing it would make every future
     * member of the stored rule a wire member by accident, and the contract is explicit about which members
     * exist.
     *
     * <p>{@code chunk_id} and {@code content_hash} are served because the contract's {@code PolicyRef} requires
     * them: this is the only route that publishes a rule, so it is the only place a run can learn what to cite
     * (C03.2b-2a). They are derived from the stored text on every read, not stored beside it.
     */
    public record Rule(
            @JsonProperty("rule_id") String ruleId,
            String title,
            String text,
            @JsonProperty("chunk_id") String chunkId,
            @JsonProperty("content_hash") String contentHash) {

        static Rule of(PolicyRule rule) {
            return new Rule(rule.ruleId(), rule.title(), rule.text(), rule.chunkId(), rule.contentHash());
        }
    }

    @GetMapping("/{bundle_id}")
    public ResponseEntity<PolicyBundleResponse> read(@PathVariable("bundle_id") String bundleId) {
        PolicyRepository.StoredBundle stored = policies.findBundle(bundleId);
        if (stored == null) {
            throw new PolicyBundleNotFoundException();
        }
        return ResponseEntity.ok(new PolicyBundleResponse(
                stored.bundleId(),
                stored.version(),
                stored.manifestHash(),
                stored.safetyEpoch(),
                policies.findRules(bundleId).stream().map(Rule::of).toList()));
    }

    /** An unknown bundle, answered with the same 404 body as everything else. */
    public static class PolicyBundleNotFoundException extends RuntimeException {

        private static final long serialVersionUID = 1L;

        public PolicyBundleNotFoundException() {
            super("no such policy bundle");
        }
    }
}
