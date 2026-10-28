package com.resolveflow.caseservice.support;

import com.resolveflow.caseservice.order.RequestPrincipalResolver;
import com.resolveflow.shared.error.ApiError;
import com.resolveflow.shared.security.Role;
import java.sql.ResultSet;
import java.sql.SQLException;
import java.time.Instant;
import java.util.*;
import org.springframework.http.ResponseEntity;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.web.bind.annotation.*;
import tools.jackson.databind.JsonNode;
import tools.jackson.databind.ObjectMapper;

/** An allowlisted operations projection. Never serializes prompts, messages or raw event payloads. */
@RestController
@RequestMapping("/api/v1/platform/support-runs")
public class SupportOperationsController {
    private final JdbcTemplate db;
    private final RequestPrincipalResolver principals;
    private final ObjectMapper json;
    private static final Set<String> CATEGORIES = Set.of("ORDER", "SHIPMENT", "POLICY", "GUIDE", "HISTORY");
    private static final Set<String> KINDS = Set.of(
            "turn.accepted",
            "activity.started",
            "activity.completed",
            "answer.started",
            "answer.reset",
            "answer.committed",
            "answer.failed",
            "answer.stale");
    private static final Set<String> REASONS = Set.of(
            "NO_PROGRESS",
            "INVALID_DECISION",
            "CONTEXT_REQUIRED_OVERFLOW",
            "UNKNOWN_MODEL_RESULT",
            "INTERRUPTED_TOOL_RESULT",
            "INPUT_CHANGED",
            "ASSISTANT_FAILED",
            "DEADLINE_EXCEEDED");

    public SupportOperationsController(JdbcTemplate db, RequestPrincipalResolver principals, ObjectMapper json) {
        this.db = db;
        this.principals = principals;
        this.json = json;
    }

    public record Event(String kind, String category, Instant created_at) {}

    public record Run(
            String run_id,
            String merchant_id,
            String status,
            String mode,
            String reason,
            Instant created_at,
            Long model_requests,
            Long tool_attempts,
            Long local_reads,
            Map<String, Integer> source_counts) {}

    public record Runs(List<Run> items, int limit) {}

    public record Detail(Run run, List<Event> events, boolean events_truncated) {}

    private void admin(String auth) {
        // session() rechecks enabled, identity_version and the persisted role, including on every detail request.
        if (principals.session(auth).principal().role() != Role.PLATFORM_ADMIN)
            throw new SupportService.Refused(403, "FORBIDDEN_SCOPE", "仅平台管理员可查看运行记录");
    }

    @GetMapping
    public Runs list(@RequestHeader(name = "Authorization", required = false) String auth) {
        admin(auth);
        return new Runs(
                db.query(
                        "SELECT t.run_id,c.merchant_id,t.status,t.reason,t.created_at,t.result_json "
                                + "FROM support_agent_turn t JOIN support_conversation c ON c.conversation_id=t.conversation_id "
                                + "ORDER BY t.created_at DESC,t.run_id DESC LIMIT 50",
                        this::run),
                50);
    }

    @GetMapping("/{id}")
    public Detail read(@RequestHeader(name = "Authorization", required = false) String auth, @PathVariable String id) {
        admin(auth);
        if (!id.matches("[0-9a-f-]{36}")) throw missing();
        var runs = db.query(
                "SELECT t.run_id,c.merchant_id,t.status,t.reason,t.created_at,t.result_json "
                        + "FROM support_agent_turn t JOIN support_conversation c ON c.conversation_id=t.conversation_id "
                        + "WHERE t.run_id=?",
                this::run,
                id);
        if (runs.isEmpty()) throw missing();
        var events = new ArrayList<>(db.query(
                "SELECT kind,payload_json,created_at FROM support_stream_event "
                        + "WHERE run_id=? AND conversation_id=(SELECT conversation_id FROM support_agent_turn WHERE run_id=?) "
                        + "AND kind IN ('turn.accepted','activity.started','activity.completed','answer.started','answer.reset',"
                        + "'answer.committed','answer.failed','answer.stale') ORDER BY event_id DESC LIMIT 201",
                (r, n) -> {
                    String kind = r.getString("kind");
                    String category = json.readTree(r.getString("payload_json"))
                            .path("category")
                            .asString("");
                    return new Event(
                            KINDS.contains(kind) ? kind : "answer.failed",
                            CATEGORIES.contains(category) ? category : null,
                            r.getTimestamp("created_at").toInstant());
                },
                id,
                id));
        boolean truncated = events.size() > 200;
        if (truncated) events.removeLast();
        Collections.reverse(events);
        return new Detail(runs.getFirst(), events, truncated);
    }

    private Run run(ResultSet r, int ignored) throws SQLException {
        String raw = r.getString("result_json");
        JsonNode result = raw == null ? json.createObjectNode() : json.readTree(raw);
        String mode = result.path("mode").asString("");
        String reason = r.getString("reason");
        var counts = new TreeMap<String, Integer>();
        for (JsonNode cite : result.path("answer").path("citations")) {
            String type = cite.path("source_type").asString("");
            if (Set.of("ORDER", "SHIPMENT", "POLICY", "KNOWLEDGE", "CONVERSATION")
                    .contains(type)) counts.merge(type, 1, Integer::sum);
        }
        return new Run(
                r.getString("run_id"),
                r.getString("merchant_id"),
                r.getString("status"),
                Set.of("live", "mock").contains(mode) ? mode : null,
                reason == null ? null : REASONS.contains(reason) ? reason : "UNAVAILABLE",
                r.getTimestamp("created_at").toInstant(),
                count(result, "model_requests"),
                count(result, "tool_attempts"),
                count(result, "local_reads"),
                counts);
    }

    private static Long count(JsonNode result, String name) {
        JsonNode value = result.path("spend").path(name);
        return value.isIntegralNumber() && value.canConvertToLong() && value.asLong() >= 0 ? value.asLong() : null;
    }

    private static SupportService.Refused missing() {
        return new SupportService.Refused(404, "NOT_FOUND", "运行记录不存在");
    }

    @ExceptionHandler(SupportService.Refused.class)
    public ResponseEntity<ApiError> refused(SupportService.Refused e) {
        return ResponseEntity.status(e.status)
                .body(ApiError.of(
                        e.code, e.getMessage(), false, UUID.randomUUID().toString()));
    }
}
