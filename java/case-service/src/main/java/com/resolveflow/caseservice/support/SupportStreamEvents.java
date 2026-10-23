package com.resolveflow.caseservice.support;

import java.util.Map;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Service;
import org.springframework.transaction.support.TransactionSynchronizationManager;
import tools.jackson.databind.ObjectMapper;

/** Local transactional event journal. It never advances a conversation's input version. */
@Service
public class SupportStreamEvents {
    private final JdbcTemplate db;
    private final ObjectMapper json;

    public SupportStreamEvents(JdbcTemplate db, ObjectMapper json) {
        this.db = db;
        this.json = json;
    }

    public void append(String conversation, String run, long input, long fence, String kind, Map<String, ?> payload) {
        if (!TransactionSynchronizationManager.isActualTransactionActive())
            throw new IllegalStateException("support events must join the business transaction");
        long previous = db.queryForObject(
                "SELECT event_sequence FROM support_conversation WHERE conversation_id=? FOR UPDATE",
                Long.class,
                conversation);
        long next = Math.addExact(previous, 1);
        db.update("UPDATE support_conversation SET event_sequence=? WHERE conversation_id=?", next, conversation);
        db.update(
                "INSERT INTO support_stream_event(conversation_id,event_id,run_id,input_version,fence,kind,payload_json) VALUES(?,?,?,?,?,?,?)",
                conversation,
                next,
                run,
                input,
                fence,
                kind,
                json.writeValueAsString(payload));
        // Bounded reconnect history; an older cursor will read an authoritative snapshot instead.
        db.update(
                "DELETE FROM support_stream_event WHERE conversation_id=? AND (event_id<=? OR created_at<TIMESTAMPADD(HOUR,-24,CURRENT_TIMESTAMP(6)))",
                conversation,
                Math.max(0, next - 512));
    }
}
