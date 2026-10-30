package com.resolveflow.caseservice.support;

import com.resolveflow.caseservice.order.RequestPrincipalResolver;
import com.resolveflow.shared.error.ApiError;
import com.resolveflow.shared.support.SupportWire.*;
import java.util.UUID;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.*;

@RestController
@RequestMapping("/api/v1/support")
public class SupportController {
    private final SupportService service;
    private final RequestPrincipalResolver principals;
    private final SupportEventStreamService streams;

    public SupportController(
            SupportService service, RequestPrincipalResolver principals, SupportEventStreamService streams) {
        this.service = service;
        this.principals = principals;
        this.streams = streams;
    }

    @PostMapping("/conversations")
    public Conversation open(
            @RequestHeader(name = "Authorization", required = false) String auth, @RequestBody Open body) {
        return service.open(principals.session(auth), body);
    }

    @GetMapping("/conversations")
    public Page<Conversation> list(
            @RequestHeader(name = "Authorization", required = false) String auth,
            @RequestParam(required = false) Integer limit,
            @RequestParam(required = false) Long before) {
        return service.list(principals.session(auth), limit, before);
    }

    @GetMapping("/conversations/{id}")
    public Conversation read(
            @RequestHeader(name = "Authorization", required = false) String auth,
            @PathVariable String id,
            @RequestParam(name = "before_sequence", required = false) Long before) {
        return service.read(principals.session(auth), id, before);
    }

    @GetMapping(value = "/conversations/{id}/events", produces = "text/event-stream")
    public org.springframework.web.servlet.mvc.method.annotation.SseEmitter events(
            @RequestHeader(name = "Authorization", required = false) String auth,
            @RequestHeader(name = "Last-Event-ID", required = false) String lastId,
            @PathVariable String id,
            jakarta.servlet.http.HttpServletResponse response) {
        var emitter = streams.stream(auth, id, lastId);
        response.setHeader("Cache-Control", "no-store");
        response.setHeader("X-Accel-Buffering", "no");
        return emitter;
    }

    @PostMapping("/conversations/{id}/messages")
    public Conversation send(
            @RequestHeader(name = "Authorization", required = false) String auth,
            @RequestHeader(name = "Idempotency-Key", required = false) String key,
            @PathVariable String id,
            @RequestBody Send body) {
        return service.send(principals.session(auth), id, key, body);
    }

    @PostMapping("/conversations/{id}/tickets")
    public Conversation handoff(
            @RequestHeader(name = "Authorization", required = false) String auth,
            @RequestHeader(name = "Idempotency-Key", required = false) String key,
            @PathVariable String id,
            @RequestBody Handoff body) {
        return service.handoff(principals.session(auth), id, key, body);
    }

    @PostMapping("/conversations/{id}/resolve")
    public Conversation resolve(
            @RequestHeader(name = "Authorization", required = false) String auth,
            @RequestHeader(name = "Idempotency-Key", required = false) String key,
            @PathVariable String id,
            @RequestBody Resolve body) {
        return service.resolve(principals.session(auth), id, key, body);
    }

    @GetMapping("/tickets")
    public Page<TicketDetail> tickets(
            @RequestHeader(name = "Authorization", required = false) String auth,
            @RequestParam(required = false) Integer limit,
            @RequestParam(required = false) Long before,
            @RequestParam(required = false) String status,
            @RequestParam(required = false) String query) {
        return service.tickets(principals.session(auth), limit, before, status, query);
    }

    @GetMapping("/tickets/{id}")
    public TicketDetail ticket(
            @RequestHeader(name = "Authorization", required = false) String auth,
            @PathVariable String id,
            @RequestParam(name = "before_sequence", required = false) Long before) {
        return service.readTicket(principals.session(auth), id, before);
    }

    @PostMapping("/tickets/{id}/messages")
    public TicketDetail reply(
            @RequestHeader(name = "Authorization", required = false) String auth,
            @RequestHeader(name = "Idempotency-Key", required = false) String key,
            @PathVariable String id,
            @RequestBody Reply body) {
        return service.reply(principals.session(auth), id, key, body);
    }

    @ExceptionHandler(SupportService.Refused.class)
    public ResponseEntity<ApiError> refused(SupportService.Refused e) {
        return ResponseEntity.status(e.status)
                .body(ApiError.of(
                        e.code, e.getMessage(), false, UUID.randomUUID().toString()));
    }
}
