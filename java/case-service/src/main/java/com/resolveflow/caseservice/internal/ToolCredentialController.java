package com.resolveflow.caseservice.internal;

import org.springframework.http.MediaType;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

/**
 * {@code POST /internal/v1/runs/{run_id}/tool-credential}: the run's scoped tool credential (C06.4④).
 *
 * <p>Declared in {@code contracts/core/openapi-case.yaml:814} since C00 and implemented here. It is on Case
 * rather than on the Agent because Case is the authority on whether the run is still the run that describes the
 * case: the contract's description says the token is bound to run/case/revision/principal/aud/scope and that a
 * renewal is issued only after Case confirms the revision is still valid, and only Case holds the case row and
 * the run binding that answer that.
 *
 * <p>Service-only, by the {@code /internal/**} filter that already guards this surface
 * ({@link ServiceTokenFilter}): a credential must not be obtainable by somebody who is merely logged in.
 *
 * <p>The path carries the run and the body carries the case and revision, which is the contract's shape. Both
 * are checked against each other, because the run id in the path and the case in the body are two statements
 * about one run and a client can make them disagree.
 */
@RestController
@RequestMapping("/internal/v1/runs")
public class ToolCredentialController {

    private final ToolCredentialService service;

    public ToolCredentialController(ToolCredentialService service) {
        this.service = service;
    }

    @PostMapping(path = "/{run_id}/tool-credential", produces = MediaType.APPLICATION_JSON_VALUE)
    public ResponseEntity<ToolCredentialResponse> issue(
            @PathVariable("run_id") String runId, @RequestBody ToolCredentialRequest request) {
        return ResponseEntity.ok(service.issue(runId, request.caseId(), request.inputRevision()));
    }
}
