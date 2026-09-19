package com.resolveflow.caseservice.auth;

import com.resolveflow.shared.security.DemoAccounts;
import java.time.Clock;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
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

    private final DemoAccounts accounts;
    private final Clock clock;

    public AuthController(DemoAccounts accounts, Clock clock) {
        this.accounts = accounts;
        this.clock = clock;
    }

    @PostMapping("/login")
    public ResponseEntity<LoginResponse> login(@RequestBody LoginRequest request) {
        DemoAccounts.Login login =
                accounts.login(request.username(), request.password(), IdentityConfiguration.now(clock));
        return ResponseEntity.status(HttpStatus.OK).body(LoginResponse.from(login));
    }
}
