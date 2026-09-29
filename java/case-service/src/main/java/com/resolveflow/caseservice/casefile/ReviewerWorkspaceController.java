package com.resolveflow.caseservice.casefile;

import com.resolveflow.caseservice.order.RequestPrincipalResolver;
import org.springframework.http.HttpHeaders;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestHeader;
import org.springframework.web.bind.annotation.RestController;

@RestController
public class ReviewerWorkspaceController {
    private final ReviewerWorkspaceService workspace;
    private final RequestPrincipalResolver principals;
    private final ReviewerInvestigationService investigations;

    public ReviewerWorkspaceController(
            ReviewerWorkspaceService workspace,
            RequestPrincipalResolver principals,
            ReviewerInvestigationService investigations) {
        this.workspace = workspace;
        this.principals = principals;
        this.investigations = investigations;
    }

    @GetMapping("/api/v1/cases/{case_id}/investigation")
    public ReviewerInvestigationService.View investigation(
            @RequestHeader(name = HttpHeaders.AUTHORIZATION, required = false) String authorization,
            @PathVariable("case_id") String caseId) {
        return investigations.read(principals.resolve(authorization), caseId);
    }

    @GetMapping("/api/v1/cases/{case_id}/review-context")
    public ReviewerWorkspaceService.Context read(
            @RequestHeader(name = HttpHeaders.AUTHORIZATION, required = false) String authorization,
            @PathVariable("case_id") String caseId) {
        return workspace.read(principals.resolve(authorization), caseId);
    }

    @PostMapping("/api/v1/cases/{case_id}/review-actions")
    public CaseSnapshotResponse act(
            @RequestHeader(name = HttpHeaders.AUTHORIZATION, required = false) String authorization,
            @RequestHeader(name = "If-Match", required = false) String ifMatch,
            @PathVariable("case_id") String caseId,
            @RequestBody ReviewerWorkspaceService.Action request) {
        return workspace.act(principals.resolve(authorization), caseId, ifMatch, request);
    }
}
