package com.resolveflow.caseservice.support;

import com.resolveflow.shared.support.SupportWire.Conversation;
import java.util.List;
import java.util.Map;
import java.util.function.Supplier;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Service;
import org.springframework.transaction.PlatformTransactionManager;
import org.springframework.transaction.TransactionDefinition;
import org.springframework.transaction.support.TransactionSynchronizationManager;
import org.springframework.transaction.support.TransactionTemplate;
import tools.jackson.databind.JsonNode;
import tools.jackson.databind.ObjectMapper;

/** Local transactional event journal. It never advances a conversation's input version. */
@Service
public class SupportStreamEvents {
    private final JdbcTemplate db;
    private final ObjectMapper json;
    private final TransactionTemplate reads;

    public SupportStreamEvents(JdbcTemplate db, ObjectMapper json, PlatformTransactionManager manager) {
        this.db = db;
        this.json = json;
        this.reads = new TransactionTemplate(manager);
        reads.setIsolationLevel(TransactionDefinition.ISOLATION_READ_COMMITTED);
    }

    public record Frame(long id, String kind, String data) {}

    /** The short shared conversation lock makes message snapshot and cursor agree. No socket I/O here. */
    public List<Frame> read(String conversation, Long cursor, Supplier<Conversation> authorizedView) {
        return reads.execute(st -> {
            var sequences = db.queryForList(
                    "SELECT event_sequence FROM support_conversation WHERE conversation_id=? FOR SHARE",
                    Long.class,
                    conversation);
            if (sequences.isEmpty()) throw new SupportService.Refused(404, "NOT_FOUND", "咨询不存在");
            long latest = sequences.getFirst();
            Conversation view = authorizedView.get();
            var ids = db.queryForList(
                    "SELECT MIN(event_id) FROM support_stream_event WHERE conversation_id=? AND created_at>=TIMESTAMPADD(HOUR,-24,CURRENT_TIMESTAMP(6))",
                    Long.class,
                    conversation);
            Long earliest = ids.getFirst();
            boolean resumable = cursor != null
                    && cursor >= 0
                    && cursor <= latest
                    && (cursor == latest || earliest != null && cursor >= earliest - 1);
            if (!resumable) {
                var payload = json.valueToTree(Map.of(
                        "conversation",
                        view,
                        "last_event_id",
                        Long.toString(latest),
                        "generation",
                        generation(conversation)));
                return List.of(frame(
                        latest,
                        conversation,
                        null,
                        view.version(),
                        null,
                        "stream.snapshot",
                        payload,
                        java.time.Instant.now().toString()));
            }
            return db.query(
                    "SELECT * FROM support_stream_event WHERE conversation_id=? AND event_id>? AND created_at>=TIMESTAMPADD(HOUR,-24,CURRENT_TIMESTAMP(6)) ORDER BY event_id LIMIT 128",
                    (r, n) -> frame(
                            r.getLong("event_id"),
                            conversation,
                            r.getString("run_id"),
                            r.getLong("input_version"),
                            r.getString("attempt_id"),
                            r.getString("kind"),
                            json.readTree(r.getString("payload_json")),
                            r.getTimestamp("created_at").toInstant().toString()),
                    conversation,
                    cursor);
        });
    }

    private Frame frame(
            long id,
            String conversation,
            String run,
            long input,
            String attempt,
            String kind,
            JsonNode payload,
            String created) {
        var node = json.createObjectNode()
                .put("event_id", Long.toString(id))
                .put("conversation_id", conversation)
                .put("run_id", run)
                .put("input_version", input)
                .put("attempt_id", attempt)
                .put("kind", kind)
                .put("created_at", created);
        node.set("payload", payload);
        return new Frame(id, kind, node.toString());
    }

    public void append(String conversation, String run, long input, long fence, String kind, Object payload) {
        append(conversation, run, input, fence, kind, payload, null);
    }

    public JsonNode generation(String conversation) {
        var rows = db.queryForList(
                "SELECT run_id,input_version,progress_json FROM support_agent_turn WHERE conversation_id=? AND status='RUNNING' AND input_version=(SELECT version FROM support_conversation WHERE conversation_id=?) ORDER BY input_version DESC LIMIT 1",
                conversation,
                conversation);
        if (rows.isEmpty() || rows.getFirst().get("progress_json") == null) return json.nullNode();
        var row = rows.getFirst();
        return json.createObjectNode()
                .put("run_id", row.get("run_id").toString())
                .put("input_version", ((Number) row.get("input_version")).longValue())
                .set("view", json.readTree(row.get("progress_json").toString()));
    }

    public void append(
            String conversation, String run, long input, long fence, String kind, Object payload, String attempt) {
        if (!TransactionSynchronizationManager.isActualTransactionActive())
            throw new IllegalStateException("support events must join the business transaction");
        long previous = db.queryForObject(
                "SELECT event_sequence FROM support_conversation WHERE conversation_id=? FOR UPDATE",
                Long.class,
                conversation);
        long next = Math.addExact(previous, 1);
        db.update("UPDATE support_conversation SET event_sequence=? WHERE conversation_id=?", next, conversation);
        db.update(
                "INSERT INTO support_stream_event(conversation_id,event_id,run_id,input_version,fence,kind,payload_json,attempt_id) VALUES(?,?,?,?,?,?,?,?)",
                conversation,
                next,
                run,
                input,
                fence,
                kind,
                json.writeValueAsString(payload),
                attempt);
        // Bounded reconnect history; an older cursor will read an authoritative snapshot instead.
        db.update(
                "DELETE FROM support_stream_event WHERE conversation_id=? AND (event_id<=? OR created_at<TIMESTAMPADD(HOUR,-24,CURRENT_TIMESTAMP(6)))",
                conversation,
                Math.max(0, next - 512));
    }
}
