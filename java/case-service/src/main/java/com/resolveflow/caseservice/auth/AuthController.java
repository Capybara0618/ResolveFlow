package com.resolveflow.caseservice.auth;

import com.resolveflow.caseservice.order.RequestPrincipalResolver;
import java.time.Clock;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestHeader;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

/**
 * The demonstration login: {@code POST /api/v1/auth/login} (docs/core-contracts.md, route table).
 *
 * <p>It is the one route that needs no token — it is how a token is obtained — and it is the only
 * place a principal is created from credentials. The endpoint has no parameter for a merchant or a
 * role: those come from the account, which is what makes "跨用户/商家不能看" enforceable later
 * (docs/core-contracts.md:15).
 */
@RestController
@RequestMapping("/api/v1/auth")
public class AuthController {

    private final PersistentAccounts accounts;
    private final Clock clock;
    private final RequestPrincipalResolver principals;

    public AuthController(PersistentAccounts accounts, Clock clock, RequestPrincipalResolver principals) {
        this.accounts = accounts;
        this.clock = clock;
        this.principals = principals;
    }

    @PostMapping("/login")
    public ResponseEntity<LoginResponse> login(@RequestBody LoginRequest request) {
        return ResponseEntity.status(HttpStatus.OK)
                .body(accounts.login(request.username(), request.password(), IdentityConfiguration.now(clock)));
    }

    @GetMapping("/me")
    public PersistentAccounts.Profile me(
            @RequestHeader(name = "Authorization", required = false) String authorization) {
        return principals.profile(authorization);
    }
}
