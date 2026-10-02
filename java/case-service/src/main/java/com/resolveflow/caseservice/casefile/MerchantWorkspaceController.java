package com.resolveflow.caseservice.casefile;

import com.resolveflow.caseservice.order.RequestPrincipalResolver;
import java.util.Map;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.RequestHeader;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

/** Administrator read surfaces; authority: docs/merchant-workspace.md. */
@RestController
@RequestMapping("/api/v1/admin")
public class MerchantWorkspaceController {
    private final RequestPrincipalResolver principals;
    private final MerchantWorkspaceService workspace;
    private final AgentRunClient agent;

    public MerchantWorkspaceController(
            RequestPrincipalResolver principals, MerchantWorkspaceService workspace, AgentRunClient agent) {
        this.principals = principals;
        this.workspace = workspace;
        this.agent = agent;
    }

    @GetMapping("/overview")
    public MerchantWorkspaceService.Overview overview(
            @RequestHeader(name = "Authorization", required = false) String auth) {
        return workspace.overview(principals.session(auth).principal());
    }

    @GetMapping("/policies")
    public MerchantWorkspaceService.PolicyList policies(
            @RequestHeader(name = "Authorization", required = false) String auth) {
        return workspace.list(principals.session(auth).principal());
    }

    @GetMapping("/policies/{bundle_id}")
    public MerchantWorkspaceService.PolicyDetail policy(
            @RequestHeader(name = "Authorization", required = false) String auth,
            @PathVariable("bundle_id") String bundle) {
        var principal = principals.session(auth).principal();
        var detail = workspace.detail(principal, bundle); // Transaction completes before the network read.
        Object index;
        try {
            index = agent.policyIndex(
                    principal.merchantId(), bundle, detail.policy().manifest_hash());
        } catch (AgentRunClient.AgentUnavailableException unavailable) {
            index = Map.of("status", "UNAVAILABLE");
        }
        return new MerchantWorkspaceService.PolicyDetail(detail.policy(), detail.rules(), index);
    }
}
