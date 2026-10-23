package com.resolveflow.caseservice.support;

import com.resolveflow.caseservice.order.RequestPrincipalResolver;
import com.resolveflow.shared.error.ApiError;
import com.resolveflow.shared.support.SupportRefundWire.*;
import java.util.UUID;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.*;

@RestController
@RequestMapping("/api/v1/support/conversations/{id}")
public class SupportRefundController {
    private final SupportRefundService refunds;
    private final RequestPrincipalResolver principals;

    public SupportRefundController(SupportRefundService refunds, RequestPrincipalResolver principals) {
        this.refunds = refunds;
        this.principals = principals;
    }

    @GetMapping("/refund-application")
    public SupportRefundService.View read(
            @RequestHeader(name = "Authorization", required = false) String auth, @PathVariable String id) {
        return refunds.read(principals.session(auth), id);
    }

    @PostMapping("/refund-drafts")
    public SupportRefundService.View prepare(
            @RequestHeader(name = "Authorization", required = false) String auth,
            @RequestHeader(name = "Idempotency-Key", required = false) String key,
            @PathVariable String id,
            @RequestBody Prepare body) {
        return refunds.prepare(principals.session(auth), id, key, body);
    }

    @PostMapping("/refund-drafts/{draftId}/edit")
    public SupportRefundService.View edit(
            @RequestHeader(name = "Authorization", required = false) String auth,
            @RequestHeader(name = "Idempotency-Key", required = false) String key,
            @PathVariable String id,
            @PathVariable String draftId,
            @RequestBody Edit body) {
        return refunds.edit(principals.session(auth), id, draftId, key, body);
    }

    @PostMapping("/refund-drafts/{draftId}/cancel")
    public SupportRefundService.View cancel(
            @RequestHeader(name = "Authorization", required = false) String auth,
            @RequestHeader(name = "Idempotency-Key", required = false) String key,
            @PathVariable String id,
            @PathVariable String draftId,
            @RequestBody Revision body) {
        return refunds.cancel(principals.session(auth), id, draftId, key, body);
    }

    @PostMapping("/refund-drafts/{draftId}/confirm")
    public SupportRefundService.View confirm(
            @RequestHeader(name = "Authorization", required = false) String auth,
            @RequestHeader(name = "Idempotency-Key", required = false) String key,
            @PathVariable String id,
            @PathVariable String draftId,
            @RequestBody Confirm body) {
        return refunds.confirm(principals.session(auth), id, draftId, key, body);
    }

    @ExceptionHandler(SupportService.Refused.class)
    public ResponseEntity<ApiError> refused(SupportService.Refused e) {
        return ResponseEntity.status(e.status)
                .body(ApiError.of(
                        e.code, e.getMessage(), false, UUID.randomUUID().toString()));
    }
}
