package com.resolveflow.caseservice.casefile;

import com.fasterxml.jackson.annotation.JsonProperty;
import com.resolveflow.shared.security.AuthenticatedPrincipal;
import java.util.List;
import org.springframework.stereotype.Service;
import tools.jackson.databind.JsonNode;

/** Read-only projection; the remote read does not hold a business transaction. */
@Service
public class ReviewerInvestigationService {
    private final CaseRepository cases;
    private final AgentRunBindingRepository bindings;
    private final AgentRunClient agent;

    public ReviewerInvestigationService(
            CaseRepository cases, AgentRunBindingRepository bindings, AgentRunClient agent) {
        this.cases = cases;
        this.bindings = bindings;
        this.agent = agent;
    }

    public record View(
            @JsonProperty("case_version") long caseVersion,
            @JsonProperty("input_revision") int inputRevision,
            String availability,
            JsonNode investigation) {}

    public View read(AuthenticatedPrincipal principal, String caseId) {
        CaseStaff.require(principal, "investigation sources are visible to merchant staff only");
        CaseRow row = cases.findCase(caseId);
        if (row == null || !row.visibleTo(principal)) throw new CaseReadService.CaseNotVisibleException();
        var binding = bindings.find(caseId, row.inputRevision());
        if (binding == null) return new View(row.version(), row.inputRevision(), "NOT_SCHEDULED", null);
        try {
            JsonNode result = agent.reviewSources(row, binding.runId());
            if (result == null
                    || !caseId.equals(result.path("case_id").asText())
                    || !binding.runId().equals(result.path("run_id").asText())
                    || row.inputRevision() != result.path("input_revision").asInt()
                    || !result.path("observations").isArray()
                    || result.path("observations").size() > 40) {
                return new View(row.version(), row.inputRevision(), "UNAVAILABLE", null);
            }
            // Keep the projection constrained even if a remote response gains internal fields later.
            var safe = new tools.jackson.databind.ObjectMapper().createObjectNode();
            for (String field : List.of(
                    "run_id", "case_id", "input_revision", "status", "model_provider", "model_id", "truncated")) {
                if (result.has(field)) safe.set(field, result.get(field));
            }
            var observations = safe.putArray("observations");
            for (JsonNode item : result.path("observations")) {
                var observation = observations.addObject();
                for (String field : List.of(
                        "call_id",
                        "observation_id",
                        "tool_name",
                        "source_type",
                        "source_ref",
                        "source_version",
                        "content_hash",
                        "observed_at",
                        "result",
                        "body_omitted",
                        "error_code")) {
                    if (item.has(field)) observation.set(field, item.get(field));
                }
            }
            return new View(row.version(), row.inputRevision(), "AVAILABLE", safe);
        } catch (AgentRunClient.AgentUnavailableException unavailable) {
            return new View(row.version(), row.inputRevision(), "UNAVAILABLE", null);
        }
    }
}
