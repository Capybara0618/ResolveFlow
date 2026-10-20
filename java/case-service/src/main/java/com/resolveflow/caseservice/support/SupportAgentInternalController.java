package com.resolveflow.caseservice.support;

import com.resolveflow.shared.error.ApiError;
import com.resolveflow.shared.security.JwtCodec;
import java.time.Clock;
import java.util.UUID;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.*;

@RestController
@RequestMapping("/internal/v1/support/turns/{run_id}")
public class SupportAgentInternalController {
    private final SupportAgentTurns turns;
    private final JwtCodec codec;
    private final Clock clock;

    public SupportAgentInternalController(SupportAgentTurns turns, JwtCodec codec, Clock clock) {
        this.turns = turns;
        this.codec = codec;
        this.clock = clock;
    }

    private JwtCodec.SupportCredential bound(String header, String id) {
        try {
            var token = codec.verifySupportCredential(header.substring(7), clock.instant());
            if (!token.runId().equals(id)) throw new IllegalArgumentException();
            return token;
        } catch (RuntimeException e) {
            throw new SupportService.Refused(403, "FORBIDDEN_SCOPE", "需要绑定咨询的只读凭据");
        }
    }

    @GetMapping("/current")
    public Object current(@RequestHeader("Authorization") String auth, @PathVariable("run_id") String id) {
        return turns.current(bound(auth, id));
    }

    @GetMapping("/facts/{kind}")
    public Object facts(
            @RequestHeader("Authorization") String auth,
            @PathVariable("run_id") String id,
            @PathVariable String kind,
            @RequestParam(name = "before_sequence", required = false) Long before,
            @RequestParam(defaultValue = "5") int limit) {
        return turns.fact(bound(auth, id), kind, before, limit);
    }

    @ExceptionHandler(SupportService.Refused.class)
    public ResponseEntity<ApiError> refused(SupportService.Refused e) {
        return ResponseEntity.status(e.status)
                .body(ApiError.of(
                        e.code, e.getMessage(), false, UUID.randomUUID().toString()));
    }

    @ExceptionHandler(com.resolveflow.caseservice.shopping.CommerceShoppingClient.Refused.class)
    public ResponseEntity<ApiError> commerceUnavailable(
            com.resolveflow.caseservice.shopping.CommerceShoppingClient.Refused e) {
        return ResponseEntity.status(e.status)
                .body(ApiError.of(
                        e.code,
                        e.getMessage(),
                        e.status >= 500,
                        UUID.randomUUID().toString()));
    }
}
