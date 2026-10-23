package com.resolveflow.caseservice.support;

import java.util.List;
import java.util.Map;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Service;
import tools.jackson.databind.JsonNode;
import tools.jackson.databind.ObjectMapper;
import tools.jackson.databind.node.ObjectNode;

/** Applies a bounded sequenced batch after the caller has locked and fenced the current turn. */
@Service
public class SupportProgress {
    private final JdbcTemplate db;
    private final ObjectMapper json;
    private final SupportStreamEvents events;

    public SupportProgress(JdbcTemplate db, ObjectMapper json, SupportStreamEvents events) {
        this.db = db;
        this.json = json;
        this.events = events;
    }

    private SupportService.Refused invalid() {
        return new SupportService.Refused(409, "PROGRESS_CONFLICT", "生成进度已更新");
    }

    public Map<String, Object> append(String conversation, String run, long input, long fence, JsonNode batch) {
        if (!batch.isObject()
                || batch.size() != 2
                || !batch.path("batch_sequence").isIntegralNumber()
                || batch.path("batch_sequence").asLong() < 1
                || !batch.path("events").isArray()
                || batch.path("events").isEmpty()
                || batch.path("events").size() > 16
                || batch.toString().length() > 16000) throw invalid();
        var row = db.queryForMap(
                "SELECT progress_sequence,progress_event_count,progress_batch_json,progress_json FROM support_agent_turn WHERE run_id=?",
                run);
        long sequence = batch.path("batch_sequence").asLong();
        long previous = ((Number) row.get("progress_sequence")).longValue();
        if (sequence == previous
                && row.get("progress_batch_json") != null
                && json.readTree(row.get("progress_batch_json").toString()).equals(batch))
            return Map.of("batch_sequence", sequence);
        if (sequence != previous + 1 || sequence > 512) throw invalid();
        int count = ((Number) row.get("progress_event_count")).intValue()
                + batch.path("events").size();
        if (count > 500) throw invalid(); // Reserve journal capacity for final lifecycle events.
        ObjectNode state = row.get("progress_json") == null
                ? json.createObjectNode()
                : (ObjectNode) json.readTree(row.get("progress_json").toString());
        for (JsonNode event : batch.path("events")) {
            if (!event.isObject()
                    || event.size() != 3
                    || !event.has("attempt_id")
                    || !event.path("kind").isString()
                    || !event.path("payload").isObject()) throw invalid();
            String kind = event.path("kind").asString();
            JsonNode payload = event.path("payload");
            String attempt = event.path("attempt_id").isString()
                    ? event.path("attempt_id").asString()
                    : null;
            switch (kind) {
                case "answer.started", "answer.reset" -> {
                    if (attempt == null || !attempt.matches("[A-Za-z0-9_-]{1,64}") || payload.size() != 0)
                        throw invalid();
                    if (kind.equals("answer.started")
                            && state.hasNonNull("attempt_id")
                            && !state.path("attempt_id").asString().equals(attempt)) throw invalid();
                    if (kind.equals("answer.reset") || !state.hasNonNull("attempt_id")) {
                        state.removeAll();
                        state.put("attempt_id", attempt);
                        state.putObject("parts");
                    }
                }
                case "answer.delta" -> {
                    if (attempt == null
                            || !attempt.equals(state.path("attempt_id").asString())
                            || payload.size() != 3
                            || !payload.path("part_id").asString().matches("part-[0-7]")
                            || !payload.path("offset").isIntegralNumber()
                            || !payload.path("text").isString()) throw invalid();
                    String part = payload.path("part_id").asString(),
                            text = payload.path("text").asString();
                    ObjectNode parts = (ObjectNode) state.path("parts");
                    String old = parts.path(part).asString("");
                    if (text.isEmpty() || payload.path("offset").asLong() != old.codePointCount(0, old.length()))
                        throw invalid();
                    parts.put(part, old + text);
                    int total = 0;
                    for (JsonNode value : parts)
                        total += value.asString()
                                .codePointCount(0, value.asString().length());
                    if (total > 4000) throw invalid();
                }
                case "activity.started", "activity.completed" -> {
                    if (attempt != null
                            || payload.size() != 1
                            || !List.of("ORDER", "SHIPMENT", "POLICY", "GUIDE", "HISTORY")
                                    .contains(payload.path("category").asString())) throw invalid();
                    if (kind.equals("activity.started")) state.set("activity", payload);
                    else state.remove("activity");
                }
                default -> throw invalid(); // Python cannot publish final messages or refund events.
            }
            events.append(conversation, run, input, fence, kind, payload, attempt);
        }
        db.update(
                "UPDATE support_agent_turn SET progress_sequence=?,progress_batch_json=?,progress_json=?,progress_event_count=? WHERE run_id=?",
                sequence,
                batch.toString(),
                state.toString(),
                count,
                run);
        return Map.of("batch_sequence", sequence);
    }
}
