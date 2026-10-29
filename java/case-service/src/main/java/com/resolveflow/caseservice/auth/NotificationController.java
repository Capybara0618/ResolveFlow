package com.resolveflow.caseservice.auth;

import com.resolveflow.caseservice.order.RequestPrincipalResolver;
import com.resolveflow.caseservice.shopping.CommerceShoppingClient.Refused;
import com.resolveflow.shared.error.ApiError;
import java.util.UUID;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.*;

@RestController
@RequestMapping("/api/v1/account/notifications")
public class NotificationController {
    private final NotificationService service;
    private final RequestPrincipalResolver principals;

    public NotificationController(NotificationService service, RequestPrincipalResolver principals) {
        this.service = service;
        this.principals = principals;
    }

    @GetMapping
    public NotificationService.Page list(
            @RequestHeader(name = "Authorization", required = false) String auth,
            @RequestParam(required = false) String cursor) {
        return service.list(principals.session(auth), cursor);
    }

    @PostMapping("/{id}/read")
    public ResponseEntity<Void> read(
            @RequestHeader(name = "Authorization", required = false) String auth, @PathVariable String id) {
        service.read(principals.session(auth), id);
        return ResponseEntity.noContent().build();
    }

    @ExceptionHandler(Refused.class)
    public ResponseEntity<ApiError> refused(Refused e) {
        return ResponseEntity.status(e.status)
                .body(ApiError.of(
                        e.code, e.getMessage(), false, UUID.randomUUID().toString()));
    }
}
