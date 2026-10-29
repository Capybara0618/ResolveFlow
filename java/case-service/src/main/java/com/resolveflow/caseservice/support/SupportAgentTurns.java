package com.resolveflow.caseservice.support;

import com.resolveflow.caseservice.casefile.CustomerCaseRepository;
import com.resolveflow.caseservice.casefile.CustomerCaseService;
import com.resolveflow.caseservice.order.CommerceOrderLineClient;
import com.resolveflow.caseservice.order.RequestPrincipalResolver.Session;
import com.resolveflow.caseservice.policy.PolicySelectionService;
import com.resolveflow.caseservice.shopping.CommerceShoppingClient;
import com.resolveflow.shared.security.AuthenticatedPrincipal;
import com.resolveflow.shared.security.JwtCodec;
import com.resolveflow.shared.security.Role;
import com.resolveflow.shared.support.SupportWire.AssistantTurn;
import java.sql.ResultSet;
import java.sql.SQLException;
import java.time.Clock;
import java.time.Instant;
import java.util.*;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Service;
import org.springframework.transaction.PlatformTransactionManager;
import org.springframework.transaction.TransactionDefinition;
import org.springframework.transaction.support.TransactionTemplate;
import org.springframework.web.client.RestClientResponseException;
import tools.jackson.databind.JsonNode;
import tools.jackson.databind.ObjectMapper;

/** Durable consultation dispatch. Network I/O is outside local transactions; publication is version/fence guarded. */
@Service
public class SupportAgentTurns {
    private final JdbcTemplate db;
    private final TransactionTemplate tx;
    private final ObjectMapper json;
    private final JwtCodec codec;
    private final CommerceOrderLineClient commerce;
    private final CommerceShoppingClient shopping;
    private final PolicySelectionService policies;
    private final SupportAgentClient agent;
    private final Clock clock;
    private final SupportStreamEvents events;
    private final SupportProgress progress;
    private final CustomerCaseRepository customerCases;
    private final CustomerCaseService buyerCases;
    private final org.springframework.context.ApplicationEventPublisher publisher;

    public record Queued() {}

    public SupportAgentTurns(
            JdbcTemplate db,
            PlatformTransactionManager manager,
            ObjectMapper json,
            JwtCodec codec,
            CommerceOrderLineClient commerce,
            CommerceShoppingClient shopping,
            PolicySelectionService policies,
            SupportAgentClient agent,
            Clock clock,
            SupportStreamEvents events,
            SupportProgress progress,
            CustomerCaseRepository customerCases,
            CustomerCaseService buyerCases,
            org.springframework.context.ApplicationEventPublisher publisher) {
        this.db = db;
        this.tx = new TransactionTemplate(manager);
        tx.setIsolationLevel(TransactionDefinition.ISOLATION_READ_COMMITTED);
        this.json = json;
        this.codec = codec;
        this.commerce = commerce;
        this.shopping = shopping;
        this.policies = policies;
        this.agent = agent;
        this.clock = clock;
        this.events = events;
        this.progress = progress;
        this.customerCases = customerCases;
        this.buyerCases = buyerCases;
        this.publisher = publisher;
    }

    private static SupportService.Refused stale() {
        return new SupportService.Refused(409, "STALE_INPUT", "咨询输入或运行已更新");
    }

    private record Turn(
            String id,
            String conversation,
            String buyer,
            String merchant,
            String customer,
            String order,
            String line,
            String actor,
            long identityVersion,
            long input,
            long fence,
            String status,
            Instant deadline,
            Instant lease,
            Instant created,
            String context,
            long version,
            String product) {}

    private static Instant instant(ResultSet rs, String key) throws SQLException {
        var value = rs.getTimestamp(key);
        return value == null ? null : value.toInstant();
    }

    private Turn row(ResultSet r, int n) throws SQLException {
        return new Turn(
                r.getString("run_id"),
                r.getString("conversation_id"),
                r.getString("buyer_id"),
                r.getString("merchant_id"),
                r.getString("customer_id"),
                r.getString("order_id"),
                r.getString("line_id"),
                r.getString("actor"),
                r.getLong("identity_version"),
                r.getLong("input_version"),
                r.getLong("fence"),
                r.getString("status"),
                instant(r, "deadline_at"),
                instant(r, "lease_until"),
                instant(r, "created_at"),
                r.getString("context_json"),
                r.getLong("conversation_version"),
                r.getString("product_json"));
    }

    private Turn find(String id) {
        var rows = db.query(
                "SELECT t.*,c.buyer_id,c.merchant_id,c.customer_id,c.order_id,c.line_id,c.product_json,c.version AS conversation_version FROM support_agent_turn t JOIN support_conversation c ON c.conversation_id=t.conversation_id WHERE t.run_id=?",
                this::row,
                id);
        if (rows.isEmpty()) throw stale();
        return rows.getFirst();
    }

    public void enqueue(Session session, String conversation, long version) {
        // Called within SupportService's message transaction, after its identity and ownership checks.
        String run = UUID.randomUUID().toString();
        db.update(
                "INSERT INTO support_agent_turn(run_id,conversation_id,input_version,actor,identity_version) VALUES(?,?,?,?,?)",
                run,
                conversation,
                version,
                session.principal().subject(),
                session.identityVersion());
        events.append(conversation, run, version, 0, "turn.accepted", Map.of("status", "PENDING"));
        publisher.publishEvent(new Queued());
    }

    /** Caller holds the conversation lock; every invalidation shares its message transaction. */
    public void invalidate(String conversation) {
        var ids = db.queryForList(
                "SELECT run_id FROM support_agent_turn WHERE conversation_id=? AND status IN ('PENDING','RUNNING')",
                String.class,
                conversation);
        for (String id : ids) {
            Turn t = find(id);
            db.update("UPDATE support_agent_turn SET status='STALE',reason='INPUT_CHANGED' WHERE run_id=?", id);
            events.append(conversation, id, t.input, t.fence, "answer.stale", Map.of("reason", "INPUT_CHANGED"));
        }
    }

    public AssistantTurn view(String conversation) {
        var rows = db.query(
                "SELECT run_id,status,reason FROM support_agent_turn WHERE conversation_id=? ORDER BY input_version DESC LIMIT 1",
                (r, n) -> new AssistantTurn(r.getString(1), r.getString(2), r.getString(3)),
                conversation);
        return rows.isEmpty() ? null : rows.getFirst();
    }

    private boolean owner(Turn t, boolean lock) {
        String suffix = lock ? " FOR SHARE" : "";
        var account = db.queryForList(
                "SELECT username FROM identity_account WHERE username=? AND buyer_id=? AND role='CUSTOMER' AND enabled=TRUE AND identity_version=?"
                        + suffix,
                String.class,
                t.actor,
                t.buyer,
                t.identityVersion);
        var store = db.queryForList(
                "SELECT merchant_id FROM identity_merchant WHERE merchant_id=? AND enabled=TRUE" + suffix,
                String.class,
                t.merchant);
        var binding = db.queryForList(
                "SELECT buyer_id FROM buyer_customer_binding WHERE buyer_id=? AND merchant_id=? AND customer_id=?"
                        + suffix,
                String.class,
                t.buyer,
                t.merchant,
                t.customer);
        return !account.isEmpty() && !store.isEmpty() && !binding.isEmpty();
    }

    private Turn lock(String id) {
        Turn t = find(id);
        owner(t, true);
        db.queryForList(
                "SELECT conversation_id FROM support_conversation WHERE conversation_id=? FOR UPDATE",
                String.class,
                t.conversation);
        db.queryForList("SELECT run_id FROM support_agent_turn WHERE run_id=? FOR UPDATE", String.class, id);
        return find(id);
    }

    public Turn claim() {
        var ids = db.queryForList(
                "SELECT run_id FROM support_agent_turn WHERE (status='PENDING' AND not_before<=CURRENT_TIMESTAMP(6)) OR (status='RUNNING' AND lease_until<CURRENT_TIMESTAMP(6)) ORDER BY created_at LIMIT 20",
                String.class);
        for (String id : ids) {
            Turn claimed = tx.execute(st -> {
                Turn t = lock(id);
                if (!owner(t, false) || t.input != t.version) {
                    markStale(t, t);
                    return null;
                }
                if (!t.status.equals("PENDING")
                        && !(t.status.equals("RUNNING") && t.lease != null && t.lease.isBefore(clock.instant())))
                    return null;
                Instant deadline = t.deadline;
                if (deadline == null) {
                    Instant cap = t.created.plusSeconds(600);
                    Instant active = clock.instant().plusSeconds(120);
                    deadline = cap.isBefore(active) ? cap : active;
                }
                db.update(
                        "UPDATE support_agent_turn SET status='RUNNING',reason=NULL,fence=fence+1,lease_until=?,deadline_at=?,progress_sequence=0,progress_batch_json=NULL,progress_json=NULL,progress_event_count=0 WHERE run_id=?",
                        java.sql.Timestamp.from(clock.instant().plusSeconds(150)),
                        java.sql.Timestamp.from(deadline),
                        id);
                events.append(t.conversation, t.id, t.input, t.fence + 1, "turn.started", Map.of("status", "RUNNING"));
                return find(id);
            });
            if (claimed != null) return claimed;
        }
        return null;
    }

    private AuthenticatedPrincipal principal(Turn t) {
        return new AuthenticatedPrincipal("support-agent", t.merchant, Role.CUSTOMER, t.customer);
    }

    private Map<String, Object> manifest(Turn t, Instant paidAt) {
        try {
            var p = policies.selectFor(t.merchant, paidAt);
            return Map.of(
                    "merchant_id",
                    p.merchantId(),
                    "bundle_ids",
                    p.bundleIds(),
                    "manifest_hash",
                    p.manifestHash(),
                    "safety_epoch",
                    p.safetyEpoch(),
                    "selected_by_paid_at",
                    p.selectedByPaidAt().toString());
        } catch (PolicySelectionService.PolicyUnavailableException e) {
            return Map.of();
        }
    }

    private List<Map<String, Object>> history(Turn t, Long before, int limit) {
        var rows = db.query(
                "SELECT message_id,sequence,author,recipient,text FROM support_message WHERE conversation_id=? AND sequence<=? AND sequence<? ORDER BY sequence DESC LIMIT ?",
                (r, n) -> Map.<String, Object>of(
                        "message_id",
                        r.getString(1),
                        "sequence",
                        r.getLong(2),
                        "author",
                        r.getString(3),
                        "recipient",
                        r.getString(4),
                        "text",
                        r.getString(5)),
                t.conversation,
                t.input,
                before == null ? Long.MAX_VALUE : before,
                limit);
        var result = new ArrayList<>(rows);
        Collections.reverse(result);
        return result;
    }

    private Turn freeze(Turn t) {
        if (t.context != null) return t;
        var lines = commerce.listByLine(principal(t), t.line).items();
        if (lines.size() != 1) throw stale();
        var line = lines.getFirst();
        var history = history(t, null, 20);
        var current = history.stream()
                .filter(m ->
                        ((Long) m.get("sequence")) == t.input && m.get("author").equals("CUSTOMER"))
                .findFirst()
                .orElseThrow(SupportAgentTurns::stale);
        Map<String, Object> context = new LinkedHashMap<>();
        context.put("product", json.readTree(t.product));
        context.put("history", history);
        context.put("history_before", history.size() == 20 ? history.getFirst().get("sequence") : null);
        context.put("current_request", current.get("text"));
        context.put("policy_manifest", manifest(t, line.paidAt()));
        return tx.execute(st -> {
            Turn live = lock(t.id);
            if (!same(t, live)) {
                markStale(live, t);
                return null;
            }
            var tickets = db.queryForList(
                    "SELECT status FROM support_ticket WHERE conversation_id=?", String.class, t.conversation);
            context.put(
                    "conversation_state",
                    Map.of(
                            "has_ticket",
                            !tickets.isEmpty(),
                            "ticket_status",
                            tickets.isEmpty() ? "NONE" : tickets.getFirst(),
                            "current_recipient",
                            current.get("recipient"),
                            "default_recipient",
                            tickets.isEmpty() ? "ASSISTANT" : "MERCHANT"));
            // Previous tasks are model hints, not facts or live source references. Freeze with this input.
            var previous = db.queryForList(
                    "SELECT input_version,result_json FROM support_agent_turn WHERE conversation_id=? AND input_version<? AND (status='SUCCEEDED' OR (status='FAILED' AND JSON_UNQUOTE(JSON_EXTRACT(result_json,'$.conversation_update.version'))='support-state-v1')) ORDER BY input_version DESC LIMIT 1",
                    t.conversation,
                    t.input);
            if (!previous.isEmpty()) {
                var row = previous.getFirst();
                var previousResult = json.readTree(row.get("result_json").toString());
                var previousAnswer = previousResult.hasNonNull("conversation_update")
                        ? previousResult.path("conversation_update")
                        : previousResult.path("answer");
                var state = previousAnswer.path("task_state");
                if (state.path("origin").asString().equals("MODEL")
                        && state.path("tasks").isArray()
                        && !state.path("tasks").isEmpty()
                        && state.path("tasks").size() <= 8
                        && state.toString().length() <= 12000) {
                    context.put(
                            "previous_tasks",
                            Map.of(
                                    "origin", "MODEL_PREVIOUS_TURN",
                                    "input_version", row.get("input_version"),
                                    "tasks", state.path("tasks")));
                }
                var memory = previousAnswer.get("customer_memory");
                if (memory != null && !memory.isNull()) {
                    long version = ((Number) row.get("input_version")).longValue();
                    if (!validCustomerMemory(t, memory, version))
                        throw new IllegalStateException("invalid persisted customer memory");
                    context.put("previous_customer_memory", memory);
                }
            }
            String encoded = json.writeValueAsString(context);
            if (live.context == null)
                db.update("UPDATE support_agent_turn SET context_json=? WHERE run_id=?", encoded, t.id);
            return find(t.id);
        });
    }

    private boolean same(Turn owned, Turn current) {
        return current.status.equals("RUNNING")
                && current.fence == owned.fence
                && current.input == current.version
                && owner(current, false);
    }

    private void markStale(Turn t, Turn owned) {
        if (t.fence != owned.fence) return;
        if (t.status.equals("RUNNING") || t.status.equals("PENDING")) {
            db.update("UPDATE support_agent_turn SET status='STALE',reason='INPUT_CHANGED' WHERE run_id=?", t.id);
            events.append(t.conversation, t.id, t.input, t.fence, "answer.stale", Map.of("reason", "INPUT_CHANGED"));
        }
    }

    public void dispatchOne() {
        Turn t = claim();
        if (t == null) return;
        try {
            t = freeze(t);
            if (t == null) return;
            var bound = new JwtCodec.SupportCredential(
                    t.id, t.conversation, t.input, t.fence, t.merchant, t.customer, t.line);
            Map<String, Object> body = new LinkedHashMap<>();
            body.put("run_id", t.id);
            body.put("conversation_id", t.conversation);
            body.put("input_version", t.input);
            body.put("merchant_id", t.merchant);
            body.put("customer_id", t.customer);
            body.put("line_id", t.line);
            body.put("deadline_at", t.deadline.toString());
            body.put("context", json.readTree(t.context));
            body.put("tool_token", codec.issueSupportCredential(bound, clock.instant()));
            body.put("progress_token", codec.issueSupportProgressCredential(bound, clock.instant()));
            String identity =
                    codec.issueServiceToken("case-service", t.merchant, t.customer, "support:run", clock.instant());
            publish(t, agent.execute(identity, body));
        } catch (RestClientResponseException e) {
            retry(t, e.getStatusCode().value() == 409 || e.getStatusCode().is5xxServerError());
        } catch (RuntimeException e) {
            retry(t, true);
        }
    }

    private void retry(Turn t, boolean retryable) {
        tx.executeWithoutResult(st -> {
            Turn live = lock(t.id);
            if (live.fence != t.fence) return;
            if (!same(t, live)) {
                markStale(live, t);
                return;
            }
            db.update(
                    "UPDATE support_agent_turn SET status=?,reason=?,not_before=TIMESTAMPADD(SECOND,3,CURRENT_TIMESTAMP(6)) WHERE run_id=?",
                    retryable ? "PENDING" : "FAILED",
                    retryable ? "ASSISTANT_UNAVAILABLE" : "AGENT_REQUEST_REJECTED",
                    t.id);
            events.append(
                    t.conversation,
                    t.id,
                    t.input,
                    t.fence,
                    retryable ? "turn.accepted" : "answer.failed",
                    Map.of("status", retryable ? "PENDING" : "FAILED"));
        });
    }

    private boolean validCustomerMemory(Turn t, JsonNode memory, long inputVersion) {
        if (!memory.isObject()
                || memory.toString().length() > 24000
                || !memory.path("version").asString().equals("support-claims-v1")
                || !memory.path("origin").asString().equals("GROUNDED_CUSTOMER_CLAIMS")
                || !memory.path("conversation_id").asString().equals(t.conversation)
                || !memory.path("merchant_id").asString().equals(t.merchant)
                || !memory.path("customer_id").asString().equals(t.customer)
                || !memory.path("line_id").asString().equals(t.line)
                || memory.path("input_version").asLong(-1) != inputVersion
                || !memory.path("entries").isArray()
                || memory.path("entries").size() > 24) return false;
        var ids = new HashSet<String>();
        for (var entry : memory.path("entries")) {
            if (!ids.add(entry.path("id").asString())
                    || !List.of("RECEIPT", "CHECKS", "REQUEST", "MATERIAL", "OTHER")
                            .contains(entry.path("topic").asString())
                    || !List.of("ACTIVE", "SUPERSEDED", "RETRACTED")
                            .contains(entry.path("status").asString())) return false;
            var source = entry.path("source");
            long sequence = source.path("sequence").asLong(-1);
            int offset = source.path("offset").asInt(-1);
            String quote = source.path("quote").asString();
            if (sequence < 1
                    || sequence > inputVersion
                    || offset < 0
                    || quote.isBlank()
                    || quote.codePointCount(0, quote.length()) > 300
                    || !quote.equals(entry.path("quote").asString())) return false;
            var originals = db.queryForList(
                    "SELECT message_id,text FROM support_message WHERE conversation_id=? AND sequence=? AND author='CUSTOMER'",
                    t.conversation,
                    sequence);
            if (originals.size() != 1) return false;
            var original = originals.getFirst();
            String text = original.get("text").toString();
            if (offset > text.codePointCount(0, text.length())
                    || !text.startsWith(quote, text.offsetByCodePoints(0, offset))) return false;
            var messageId = source.get("message_id");
            if (messageId != null
                    && !messageId.isNull()
                    && !messageId.asString().equals(original.get("message_id").toString())) return false;
        }
        return true;
    }

    private boolean validConversationUpdate(Turn t, JsonNode update) {
        if (update == null || update.isNull()) return true; // Old wire remains compatible.
        if (!update.isObject()
                || update.toString().length() > 65536
                || !update.path("version").asString().equals("support-state-v1")
                || !update.path("run_id").asString().equals(t.id)
                || !update.path("conversation_id").asString().equals(t.conversation)
                || !update.path("merchant_id").asString().equals(t.merchant)
                || !update.path("customer_id").asString().equals(t.customer)
                || !update.path("line_id").asString().equals(t.line)
                || update.path("input_version").asLong(-1) != t.input
                || !validCustomerMemory(t, update.path("customer_memory"), t.input)) return false;
        var state = update.path("task_state");
        var tasks = state.path("tasks");
        if (!state.path("origin").asString().equals("MODEL") || !tasks.isArray() || tasks.size() > 8) return false;
        var ids = new HashSet<String>();
        for (var task : tasks) {
            String id = task.path("id").asString();
            if (!id.matches("^[a-zA-Z0-9_-]{1,32}$")
                    || !ids.add(id)
                    || !List.of("LOGISTICS", "ELIGIBILITY", "APPLICATION", "HANDOFF", "PRODUCT", "OTHER")
                            .contains(task.path("intent").asString())
                    || !List.of(
                                    "PENDING",
                                    "ANSWERED",
                                    "NEEDS_CUSTOMER",
                                    "NEEDS_MERCHANT",
                                    "UNAVAILABLE",
                                    "CANCELLED",
                                    "SUSPENDED")
                            .contains(task.path("status").asString())
                    || !List.of("OPEN", "PAUSED", "RESOLVED", "CANCELLED")
                            .contains(task.path("lifecycle").asString())
                    || !task.path("evidence_refs").isArray()
                    || !task.path("evidence_refs").isEmpty()
                    || !task.path("response_excerpt").isNull()) return false;
        }
        var events = update.path("dialogue_state").path("events");
        if (!events.isArray() || events.size() > 96) return false;
        for (var event : events) {
            if (!ids.contains(event.path("task_id").asString())
                    || !List.of(
                                    "ADD",
                                    "CONTINUE",
                                    "CORRECT",
                                    "CANCEL",
                                    "PAUSE",
                                    "RESUME",
                                    "CLARIFY",
                                    "RESOLVE",
                                    "REOPEN")
                            .contains(event.path("change").asString())) return false;
            var source = event.path("source");
            String quote = source.path("quote").asString();
            int offset = source.path("offset").asInt(-1);
            if (source.path("sequence").asLong(-1) != t.input
                    || offset < 0
                    || quote.isBlank()
                    || quote.codePointCount(0, quote.length()) > 300) return false;
            var originals = db.queryForList(
                    "SELECT text FROM support_message WHERE conversation_id=? AND sequence=? AND author='CUSTOMER'",
                    String.class,
                    t.conversation,
                    t.input);
            if (originals.size() != 1) return false;
            String text = originals.getFirst();
            if (offset > text.codePointCount(0, text.length())
                    || !text.startsWith(quote, text.offsetByCodePoints(0, offset))) return false;
        }
        return true;
    }

    private boolean validResult(Turn t, JsonNode result) {
        if (result == null
                || !result.isObject()
                || !t.id.equals(result.path("run_id").asString())
                || !t.conversation.equals(result.path("conversation_id").asString())
                || result.path("input_version").asLong() != t.input
                || !validConversationUpdate(t, result.get("conversation_update"))) return false;
        if (result.path("status").asString().equals("FAILED")) return true;
        if (!result.path("status").asString().equals("SUCCEEDED")
                || !List.of("mock", "live").contains(result.path("mode").asString())) return false;
        var answer = result.path("answer");
        var memory = answer.get("customer_memory");
        if (memory != null && !memory.isNull() && !validCustomerMemory(t, memory, t.input)) return false;
        var text = answer.path("text");
        if (!text.isString() || text.asString().isBlank() || text.asString().length() > 4000) return false;
        var citations = answer.path("citations");
        if (!citations.isArray() || citations.size() > 8) return false;
        for (var cite : citations) {
            if (!cite.path("source_id").asString().matches("[OP][1-9][0-9]*")
                    || !cite.path("content_hash").asString().matches("[a-f0-9]{64}")
                    || !List.of("ORDER", "SHIPMENT", "CONVERSATION", "POLICY", "KNOWLEDGE")
                            .contains(cite.path("source_type").asString())) return false;
            if (cite.path("source_type").asString().equals("POLICY")
                    && (!t.merchant.equals(cite.path("data").path("merchant_id").asString())
                            || !json.readTree(t.context)
                                    .path("policy_manifest")
                                    .path("manifest_hash")
                                    .asString()
                                    .equals(cite.path("data")
                                            .path("manifest_hash")
                                            .asString()))) return false;
        }
        var summary = answer.get("handoff_summary");
        var refundSummary = answer.get("refund_summary");
        if (!SupportBuyerView.valid(answer)) return false;
        if (refundSummary != null
                && !refundSummary.isNull()
                && (!refundSummary.isString()
                        || refundSummary.asString().isBlank()
                        || refundSummary.asString().length() > 2000)) return false;
        return summary == null
                || summary.isNull()
                || (summary.isString()
                        && !summary.asString().isBlank()
                        && summary.asString().length() <= 2000);
    }

    private void publish(Turn owned, JsonNode result) {
        tx.executeWithoutResult(st -> {
            Turn live = lock(owned.id);
            if (live.fence != owned.fence) return;
            if (!same(owned, live)) {
                markStale(live, owned);
                return;
            }
            if (!validResult(live, result)) {
                db.update(
                        "UPDATE support_agent_turn SET status='FAILED',reason='AGENT_PROTOCOL_INVALID' WHERE run_id=?",
                        live.id);
                events.append(
                        live.conversation,
                        live.id,
                        live.input,
                        live.fence,
                        "answer.failed",
                        Map.of("reason", "ASSISTANT_FAILED"));
                return;
            }
            if (result.path("status").asString().equals("FAILED")) {
                db.update(
                        "UPDATE support_agent_turn SET status='FAILED',reason=?,result_json=? WHERE run_id=?",
                        result.path("reason")
                                .asString("ASSISTANT_FAILED")
                                .substring(
                                        0,
                                        Math.min(
                                                128,
                                                result.path("reason")
                                                        .asString("ASSISTANT_FAILED")
                                                        .length())),
                        result.toString(),
                        live.id);
                events.append(
                        live.conversation,
                        live.id,
                        live.input,
                        live.fence,
                        "answer.failed",
                        Map.of("reason", "ASSISTANT_FAILED"));
                return;
            }
            var answer = result.path("answer");
            var metadata = json.createObjectNode();
            metadata.put("run_id", live.id);
            metadata.put("mode", result.path("mode").asString());
            metadata.set("citations", answer.get("citations"));
            metadata.set(
                    "handoff_summary", answer.has("handoff_summary") ? answer.get("handoff_summary") : json.nullNode());
            if (answer.hasNonNull("refund_summary")) metadata.set("refund_summary", answer.get("refund_summary"));
            if (answer.has("buyer_view")) metadata.set("buyer_view", answer.get("buyer_view"));
            String messageId = UUID.randomUUID().toString();
            db.update(
                    "INSERT INTO support_message(message_id,conversation_id,sequence,author,recipient,actor,text,assistant_json) VALUES(?,?,?,'ASSISTANT','CUSTOMER','agent-service',?,?)",
                    messageId,
                    live.conversation,
                    live.input + 1,
                    answer.path("text").asString(),
                    metadata.toString());
            db.update("UPDATE support_conversation SET version=version+1 WHERE conversation_id=?", live.conversation);
            db.update(
                    "UPDATE support_agent_turn SET status='SUCCEEDED',reason=NULL,result_json=? WHERE run_id=?",
                    result.toString(),
                    live.id);
            events.append(
                    live.conversation,
                    live.id,
                    live.input,
                    live.fence,
                    "answer.committed",
                    Map.of(
                            "message_id",
                            messageId,
                            "sequence",
                            live.input + 1,
                            "text",
                            answer.path("text").asString(),
                            "assistant",
                            metadata));
        });
    }

    public Map<String, Object> current(JwtCodec.SupportCredential token) {
        Turn t = find(token.runId());
        if (!t.conversation.equals(token.conversationId())
                || !t.merchant.equals(token.merchantId())
                || !t.customer.equals(token.customerId())
                || !t.line.equals(token.lineId()))
            throw new SupportService.Refused(403, "FORBIDDEN_SCOPE", "咨询读取身份不匹配");
        if (!t.status.equals("RUNNING")
                || t.fence != token.fence()
                || t.input != token.inputVersion()
                || t.input != t.version
                || t.lease == null
                || !t.lease.isAfter(clock.instant())
                || !owner(t, false)) throw stale();
        return Map.of("conversation_id", t.conversation, "input_version", t.input);
    }

    public Object progress(JwtCodec.SupportCredential token, JsonNode batch) {
        return tx.execute(st -> {
            Turn t = lock(token.runId());
            current(token);
            return progress.append(t.conversation, t.id, t.input, t.fence, batch);
        });
    }

    public Object fact(JwtCodec.SupportCredential token, String kind, Long before, int limit) {
        current(token);
        Turn t = find(token.runId());
        if (kind.equals("order")) {
            var lines = commerce.listByLine(principal(t), t.line).items();
            if (lines.size() != 1) throw stale();
            // The independent inquiry ticket says nothing about a refund application.
            // Reuse the buyer projection, scoped to this credential's merchant/customer/line.
            var related = customerCases.related(t.merchant, t.customer, t.line);
            Map<String, Object> application = new LinkedHashMap<>();
            application.put("present", related != null);
            application.put("status", "NONE");
            String applicationVersion = "none";
            if (related != null) {
                var detail = buyerCases.read(principal(t), related.caseId());
                var summary = detail.caseSummary();
                applicationVersion = summary.caseId() + ":" + summary.version();
                application.put("case_id", summary.caseId());
                application.put("line_id", summary.lineId());
                application.put("version", summary.version());
                application.put("status", detail.result().status().name());
                application.put("message", detail.result().message());
                application.put("amount_minor", detail.result().amountMinor());
                application.put("currency", detail.result().currency());
                application.put("allowed_actions", detail.allowedActions());
                application.put("blocked_reason", detail.blockedReason());
            }
            return Map.of(
                    "merchant_id",
                    t.merchant,
                    "line_id",
                    t.line,
                    "version",
                    "order-" + lines.getFirst().version() + ":refund-" + applicationVersion,
                    "order_line",
                    lines.getFirst(),
                    "refund_application",
                    application);
        }
        if (kind.equals("shipment")) {
            var result = shopping.fulfillment(t.order, t.merchant, t.customer);
            return Map.of(
                    "order_id",
                    t.order,
                    "synthetic",
                    result.synthetic(),
                    "status",
                    result.status(),
                    "version",
                    result.version() == null ? 0 : result.version(),
                    "lines",
                    result.lines().stream()
                            .filter(l -> l.lineId().equals(t.line))
                            .toList());
        }
        if (kind.equals("history")) {
            if (limit < 1 || limit > 5 || before != null && before < 1)
                throw new SupportService.Refused(400, "INVALID_ARGUMENT", "历史分页无效");
            return Map.of("messages", history(t, before, limit), "version", t.input);
        }
        throw new SupportService.Refused(404, "NOT_FOUND", "不支持的咨询来源");
    }
}
