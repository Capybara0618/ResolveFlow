package com.resolveflow.caseservice.casefile;

import com.resolveflow.caseservice.order.RequestPrincipalResolver;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestHeader;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

@RestController
@RequestMapping("/api/v1/cases/{case_id}/collaboration")
public class CaseCollaborationController {
    private final CaseCollaborationService collaborations;
    private final RequestPrincipalResolver principals;

    public CaseCollaborationController(CaseCollaborationService collaborations, RequestPrincipalResolver principals) {
        this.collaborations = collaborations;
        this.principals = principals;
    }

    @GetMapping
    public CaseCollaborationService.View read(
            @RequestHeader(name = "Authorization", required = false) String authorization,
            @PathVariable("case_id") String caseId) {
        return collaborations.read(principals.resolve(authorization), caseId);
    }

    @PostMapping
    public CaseCollaborationService.View act(
            @RequestHeader(name = "Authorization", required = false) String authorization,
            @RequestHeader(name = "If-Collaboration-Match", required = false) String ifMatch,
            @PathVariable("case_id") String caseId,
            @RequestBody CaseCollaborationService.Action request) {
        var session = principals.session(authorization);
        return collaborations.act(session.principal(), session.identityVersion(), caseId, ifMatch, request);
    }
}
