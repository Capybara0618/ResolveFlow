package com.resolveflow.caseservice.support;

import com.resolveflow.caseservice.auth.AvatarStore;
import com.resolveflow.caseservice.order.RequestPrincipalResolver;
import com.resolveflow.caseservice.order.RequestPrincipalResolver.Session;
import com.resolveflow.caseservice.shopping.CommerceShoppingClient.Refused;
import com.resolveflow.shared.error.ApiError;
import com.resolveflow.shared.security.Role;
import java.util.ArrayList;
import java.util.UUID;
import org.springframework.http.ResponseEntity;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.web.bind.annotation.*;

/** Resolves only authors of messages already visible through the consultation's own projection. */
@RestController
@RequestMapping("/api/v1/support/conversations/{conversation}/messages/{message}/identity")
public class SupportIdentityController {
    public record Identity(String display_name, String avatar_id, String author) {}

    private final JdbcTemplate db;
    private final SupportService support;
    private final RequestPrincipalResolver principals;
    private final AvatarStore avatars;

    public SupportIdentityController(
            JdbcTemplate db, SupportService support, RequestPrincipalResolver principals, AvatarStore avatars) {
        this.db = db;
        this.support = support;
        this.principals = principals;
        this.avatars = avatars;
    }

    private Identity identity(Session s, String conversation, String message) {
        var sequence = db.queryForList(
                "SELECT sequence FROM support_message WHERE conversation_id=? AND message_id=?",
                Long.class,
                conversation,
                message);
        if (sequence.isEmpty()) throw missing();
        var visible = new ArrayList<com.resolveflow.shared.support.SupportWire.Message>();
        if (s.principal().isPlatformBuyer())
            visible.addAll(
                    support.read(s, conversation, sequence.getFirst() + 1).messages());
        else if (s.principal().role() == Role.MERCHANT_ADMIN) {
            var ids = db.queryForList(
                    "SELECT ticket_id FROM support_ticket WHERE conversation_id=? AND merchant_id=?",
                    String.class,
                    conversation,
                    s.principal().merchantId());
            if (ids.isEmpty()) throw missing();
            var detail = support.readTicket(s, ids.getFirst(), sequence.getFirst() + 1);
            visible.addAll(detail.messages());
            visible.addAll(detail.ticket().sharedMessages());
        } else throw missing();
        var m = visible.stream()
                .filter(v -> v.messageId().equals(message))
                .findFirst()
                .orElseThrow(SupportIdentityController::missing);
        if (m.author().equals("ASSISTANT")) return new Identity("售后助手", null, "ASSISTANT");
        var values = db.query(
                "SELECT a.display_name,a.avatar_id FROM support_message m JOIN identity_account a ON a.username=m.actor WHERE m.conversation_id=? AND m.message_id=?",
                (r, n) -> new Identity(r.getString(1), r.getString(2), m.author()),
                conversation,
                message);
        return values.isEmpty()
                ? new Identity(m.author().equals("MERCHANT") ? "商家" : "买家", null, m.author())
                : values.getFirst();
    }

    private static Refused missing() {
        return new Refused(404, "NOT_FOUND", "消息不存在");
    }

    @GetMapping
    public Identity read(
            @RequestHeader(name = "Authorization", required = false) String auth,
            @PathVariable String conversation,
            @PathVariable String message) {
        return identity(principals.session(auth), conversation, message);
    }

    @GetMapping(value = "/avatar", produces = "image/png")
    public ResponseEntity<byte[]> image(
            @RequestHeader(name = "Authorization", required = false) String auth,
            @PathVariable String conversation,
            @PathVariable String message) {
        var i = identity(principals.session(auth), conversation, message);
        if (i.avatar_id() == null) throw missing();
        return ResponseEntity.ok()
                .header("Cache-Control", "private, no-store")
                .header("X-Content-Type-Options", "nosniff")
                .body(avatars.read(i.avatar_id()));
    }

    @ExceptionHandler(Refused.class)
    public ResponseEntity<ApiError> refused(Refused e) {
        return ResponseEntity.status(e.status)
                .body(ApiError.of(
                        e.code, e.getMessage(), false, UUID.randomUUID().toString()));
    }

    @ExceptionHandler(SupportService.Refused.class)
    public ResponseEntity<ApiError> refusedSupport(SupportService.Refused e) {
        return ResponseEntity.status(e.status)
                .body(ApiError.of(
                        e.code, e.getMessage(), false, UUID.randomUUID().toString()));
    }
}
