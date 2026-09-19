package com.resolveflow.caseservice.casefile;

import com.resolveflow.caseservice.order.RequestPrincipalResolver;
import com.resolveflow.shared.security.AuthenticatedPrincipal;
import java.net.URI;
import org.springframework.http.HttpHeaders;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestHeader;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

/**
 * {@code POST /api/v1/cases} (docs/core-contracts.md:28).
 *
 * <p>The controller does three things and no more: resolve the principal, hand the decision to the
 * service, and answer 201 with the {@code Location} of the case the contract declares. Every rule
 * about who may open a case, what a repeated key means and when a line is invisible lives in the
 * service, where it can be tested without HTTP.
 */
@RestController
@RequestMapping("/api/v1/cases")
public class CaseController {

    private final CaseService cases;
    private final CaseReadService reads;
    private final RequestPrincipalResolver principals;

    public CaseController(CaseService cases, CaseReadService reads, RequestPrincipalResolver principals) {
        this.cases = cases;
        this.reads = reads;
        this.principals = principals;
    }

    @PostMapping
    public ResponseEntity<CaseCreatedResponse> create(
            @RequestHeader(name = HttpHeaders.AUTHORIZATION, required = false) String authorization,
            @RequestHeader(name = "Idempotency-Key", required = false) String idempotencyKey,
            @RequestBody CaseCreateRequest request) {
        AuthenticatedPrincipal principal = principals.resolve(authorization);
        CaseService.Created created = cases.create(principal, idempotencyKey, request);
        return ResponseEntity.created(
                        URI.create("/api/v1/cases/" + created.body().caseId()))
                .body(created.body());
    }

    @GetMapping("/{case_id}")
    public ResponseEntity<CaseSnapshotResponse> read(
            @RequestHeader(name = HttpHeaders.AUTHORIZATION, required = false) String authorization,
            @PathVariable("case_id") String caseId) {
        AuthenticatedPrincipal principal = principals.resolve(authorization);
        return ResponseEntity.ok(reads.read(principal, caseId));
    }
}
