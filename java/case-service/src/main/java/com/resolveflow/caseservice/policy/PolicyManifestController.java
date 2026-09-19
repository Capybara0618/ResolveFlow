package com.resolveflow.caseservice.policy;

import com.fasterxml.jackson.annotation.JsonInclude;
import com.fasterxml.jackson.annotation.JsonProperty;
import com.resolveflow.caseservice.casefile.CaseRepository;
import java.time.Instant;
import java.util.List;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

/**
 * The policy manifest a case is pinned to (docs/core-contracts.md:50).
 *
 * <p>This is what a run is opened against: the Agent is told which bundles and which hash it must cite, and
 * a case never silently switches to a newer policy. The answer is read from the case, not re-derived from
 * the policy table — re-deriving it would answer with today's choice and make the pinning look pointless.
 *
 * <p>Two not-found cases share the route's 404 with distinct messages: no such case, and a case with no
 * pinned manifest. The second one is a real state for cases opened before this table existed, and it is
 * answered rather than back-filled — the payment time a manifest would have to be chosen by is not stored
 * on the case, so any back-fill would be a guess about which policy decided it.
 */
@RestController
@RequestMapping("/internal/v1/cases")
public class PolicyManifestController {

    private final PolicyManifestRepository manifests;
    private final CaseRepository cases;

    public PolicyManifestController(PolicyManifestRepository manifests, CaseRepository cases) {
        this.manifests = manifests;
        this.cases = cases;
    }

    /** The contract's {@code PolicyManifestResponse}. */
    @JsonInclude(JsonInclude.Include.NON_NULL)
    public record PolicyManifestResponse(
            List<Bundle> bundles,
            @JsonProperty("effective_from") Instant effectiveFrom,
            @JsonProperty("effective_to") Instant effectiveTo) {}

    /** One manifest hash, covering one or more bundles. */
    @JsonInclude(JsonInclude.Include.NON_NULL)
    public record Bundle(
            @JsonProperty("bundle_ids") List<String> bundleIds,
            @JsonProperty("manifest_hash") String manifestHash,
            @JsonProperty("safety_epoch") int safetyEpoch) {}

    @GetMapping("/{case_id}/policy-manifest")
    public ResponseEntity<PolicyManifestResponse> read(@PathVariable("case_id") String caseId) {
        if (cases.findCase(caseId) == null) {
            throw new PolicyManifestNotFoundException("no such case");
        }
        PolicyManifestRepository.StoredManifest stored = manifests.findManifest(caseId);
        if (stored == null) {
            throw new PolicyManifestNotFoundException("this case has no pinned policy manifest");
        }
        return ResponseEntity.ok(new PolicyManifestResponse(
                List.of(new Bundle(manifests.findBundleIds(caseId), stored.manifestHash(), stored.safetyEpoch())),
                stored.effectiveFrom(),
                stored.effectiveTo()));
    }

    /** The case is unknown, or it carries no pinned manifest. */
    public static class PolicyManifestNotFoundException extends RuntimeException {

        private static final long serialVersionUID = 1L;

        public PolicyManifestNotFoundException(String message) {
            super(message);
        }
    }
}
