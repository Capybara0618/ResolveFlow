package com.resolveflow.caseservice.support;

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

    public SupportAgentTurns(
            JdbcTemplate db,
            PlatformTransactionManager manager,
            ObjectMapper json,
            JwtCodec codec,
            CommerceOrderLineClient commerce,
            CommerceShoppingClient shopping,
            PolicySelectionService policies,
            SupportAgentClient agent,
            Clock clock) {
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
        db.update(
                "INSERT INTO support_agent_turn(run_id,conversation_id,input_version,actor,identity_version) VALUES(?,?,?,?,?)",
                UUID.randomUUID().toString(),
                conversation,
                version,
                session.principal().subject(),
                session.identityVersion());
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
                    db.update("UPDATE support_agent_turn SET status='STALE',reason='INPUT_CHANGED' WHERE run_id=?", id);
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
                        "UPDATE support_agent_turn SET status='RUNNING',reason=NULL,fence=fence+1,lease_until=?,deadline_at=? WHERE run_id=?",
                        java.sql.Timestamp.from(clock.instant().plusSeconds(150)),
                        java.sql.Timestamp.from(deadline),
                        id);
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
        String encoded = json.writeValueAsString(context);
        return tx.execute(st -> {
            Turn live = lock(t.id);
            if (!same(t, live)) {
                markStale(live, t);
                return null;
            }
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
        if (t.status.equals("RUNNING") || t.status.equals("PENDING"))
            db.update("UPDATE support_agent_turn SET status='STALE',reason='INPUT_CHANGED' WHERE run_id=?", t.id);
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
        });
    }

    private boolean validResult(Turn t, JsonNode result) {
        if (result == null
                || !result.isObject()
                || !t.id.equals(result.path("run_id").asString())
                || !t.conversation.equals(result.path("conversation_id").asString())
                || result.path("input_version").asLong() != t.input) return false;
        if (result.path("status").asString().equals("FAILED")) return true;
        if (!result.path("status").asString().equals("SUCCEEDED")
                || !List.of("mock", "live").contains(result.path("mode").asString())) return false;
        var answer = result.path("answer");
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
                return;
            }
            var answer = result.path("answer");
            var metadata = json.createObjectNode();
            metadata.put("run_id", live.id);
            metadata.put("mode", result.path("mode").asString());
            metadata.set("citations", answer.get("citations"));
            metadata.set(
                    "handoff_summary", answer.has("handoff_summary") ? answer.get("handoff_summary") : json.nullNode());
            db.update(
                    "INSERT INTO support_message(message_id,conversation_id,sequence,author,recipient,actor,text,assistant_json) VALUES(?,?,?,'ASSISTANT','CUSTOMER','agent-service',?,?)",
                    UUID.randomUUID().toString(),
                    live.conversation,
                    live.input + 1,
                    answer.path("text").asString(),
                    metadata.toString());
            db.update("UPDATE support_conversation SET version=version+1 WHERE conversation_id=?", live.conversation);
            db.update(
                    "UPDATE support_agent_turn SET status='SUCCEEDED',reason=NULL,result_json=? WHERE run_id=?",
                    result.toString(),
                    live.id);
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

    public Object fact(JwtCodec.SupportCredential token, String kind, Long before, int limit) {
        current(token);
        Turn t = find(token.runId());
        if (kind.equals("order")) {
            var lines = commerce.listByLine(principal(t), t.line).items();
            if (lines.size() != 1) throw stale();
            return Map.of(
                    "merchant_id",
                    t.merchant,
                    "line_id",
                    t.line,
                    "version",
                    lines.getFirst().version(),
                    "order_line",
                    lines.getFirst());
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
