package com.resolveflow.caseservice.auth;

import com.resolveflow.caseservice.order.RequestPrincipalResolver;
import com.resolveflow.caseservice.shopping.CommerceShoppingClient.Refused;
import com.resolveflow.shared.error.ApiError;
import com.resolveflow.shared.security.IdentityAccessWire.*;
import com.resolveflow.shared.security.Role;
import java.util.List;
import java.util.UUID;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.*;

/** Account-only internal API. No trading reads and no caller-selected merchant/customer scope. */
@RestController
@RequestMapping("/internal/v1/identity")
public class IdentityAccessController {
    private final RequestPrincipalResolver principals;
    private final BuyerScopes scopes;
    private final AccountService accounts;

    public IdentityAccessController(RequestPrincipalResolver principals, BuyerScopes scopes, AccountService accounts) {
        this.principals = principals;
        this.scopes = scopes;
        this.accounts = accounts;
    }

    @PostMapping("/resolve")
    public ResponseEntity<Context> resolve(@RequestBody Resolve request) {
        if (request.user_authorization() == null || request.user_authorization().length() > 8192)
            throw new RequestPrincipalResolver.UnauthenticatedException("a valid user token is required");
        var session = principals.session(request.user_authorization());
        var p = session.principal();
        if (p.role() == Role.PLATFORM_ADMIN) throw new Refused(403, "FORBIDDEN_SCOPE", "平台管理员无交易权限");
        var bindings = p.isPlatformBuyer()
                ? scopes.list(p).stream()
                        .map(s -> new Binding(s.merchantId(), s.customerId(), s.merchantName()))
                        .toList()
                : List.<Binding>of();
        if (bindings.size() > 20) throw new Refused(503, "UPSTREAM_UNAVAILABLE", "账号关联范围超出支持上限");
        var shipping = request.shipping() == null ? null : accounts.shipping(session, request.shipping());
        return ResponseEntity.ok()
                .header("Cache-Control", "no-store")
                .body(new Context(
                        p.subject(),
                        p.merchantId(),
                        p.role(),
                        p.customerId(),
                        p.buyerId(),
                        session.identityVersion(),
                        bindings,
                        shipping));
    }

    @ExceptionHandler(Refused.class)
    public ResponseEntity<ApiError> refused(Refused error) {
        return ResponseEntity.status(error.status)
                .body(ApiError.of(
                        error.code, error.getMessage(), false, UUID.randomUUID().toString()));
    }
}
