package com.resolveflow.caseservice.internal;

import com.fasterxml.jackson.annotation.JsonInclude;
import com.fasterxml.jackson.annotation.JsonProperty;
import com.resolveflow.caseservice.casefile.AgentCallback;
import com.resolveflow.caseservice.casefile.AgentCallbackService;
import org.springframework.http.MediaType;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

/**
 * {@code POST /internal/v1/cases/{case_id}/agent-callbacks}: what a run tells the case.
 *
 * <p>Service-only, and the case is in the path because the delivery is about one case: a callback that named
 * no case would be a run reporting into the void. The body repeats {@code run_id} and {@code input_revision}
 * because the contract carries them (the Agent's run identity and the revision it decided on), and this
 * service records both — which run delivered, and whether that revision is still current.
 *
 * <p>The response is the contract's {@code AgentCallbackResponse}: the disposition, and the case version only
 * when this delivery produced one.
 */
@RestController
@RequestMapping("/internal/v1/cases")
public class AgentCallbackController {

    private final AgentCallbackService service;

    public AgentCallbackController(AgentCallbackService service) {
        this.service = service;
    }

    @PostMapping(path = "/{case_id}/agent-callbacks", produces = MediaType.APPLICATION_JSON_VALUE)
    public ResponseEntity<AgentCallbackResponse> receive(
            @PathVariable("case_id") String caseId, @RequestBody AgentCallbackRequest request) {
        AgentCallbackService.Receipt receipt = service.receive(caseId, request);
        return ResponseEntity.ok(new AgentCallbackResponse(receipt.disposition(), receipt.caseVersion()));
    }

    /** {@code case_version} is absent exactly when the delivery changed nothing. */
    @JsonInclude(JsonInclude.Include.NON_NULL)
    public record AgentCallbackResponse(
            @JsonProperty("disposition") AgentCallback.Disposition disposition,
            @JsonProperty("case_version") Long caseVersion) {}
}
