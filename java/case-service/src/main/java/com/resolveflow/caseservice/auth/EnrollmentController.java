package com.resolveflow.caseservice.auth;

import com.resolveflow.caseservice.order.RequestPrincipalResolver;
import com.resolveflow.caseservice.shopping.CommerceShoppingClient.Refused;
import com.resolveflow.shared.error.ApiError;
import jakarta.servlet.http.HttpServletRequest;
import java.util.UUID;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.*;

@RestController
public class EnrollmentController {
    private final EnrollmentService service;
    private final RequestPrincipalResolver principals;

    public EnrollmentController(EnrollmentService service, RequestPrincipalResolver principals) {
        this.service = service;
        this.principals = principals;
    }

    @PostMapping("/api/v1/auth/register")
    public ResponseEntity<EnrollmentService.Receipt> register(
            @RequestBody EnrollmentService.Register body, HttpServletRequest request) {
        return ResponseEntity.status(201)
                .header("Cache-Control", "no-store")
                .body(service.register(body, request.getRemoteAddr()));
    }

    @PostMapping("/api/v1/auth/recover")
    public ResponseEntity<EnrollmentService.Receipt> recover(
            @RequestBody EnrollmentService.Recover body, HttpServletRequest request) {
        return ResponseEntity.ok()
                .header("Cache-Control", "no-store")
                .body(service.recover(body, request.getRemoteAddr()));
    }

    @PostMapping("/api/v1/account/login-name")
    public ResponseEntity<EnrollmentService.LoginChanged> changeLogin(
            @RequestHeader(name = "Authorization", required = false) String auth,
            @RequestBody EnrollmentService.ChangeLogin body) {
        return ResponseEntity.ok()
                .header("Cache-Control", "no-store")
                .body(service.changeLogin(principals.session(auth), body));
    }

    @PostMapping("/api/v1/account/recovery-key")
    public ResponseEntity<EnrollmentService.Receipt> rotate(
            @RequestHeader(name = "Authorization", required = false) String auth,
            @RequestBody EnrollmentService.Rotate body) {
        return ResponseEntity.ok()
                .header("Cache-Control", "no-store")
                .body(service.rotate(principals.session(auth), body));
    }

    @ExceptionHandler(Refused.class)
    public ResponseEntity<ApiError> refused(Refused e) {
        return ResponseEntity.status(e.status)
                .body(ApiError.of(
                        e.code, e.getMessage(), false, UUID.randomUUID().toString()));
    }
}
