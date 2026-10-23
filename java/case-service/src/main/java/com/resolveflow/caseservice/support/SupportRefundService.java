package com.resolveflow.caseservice.support;

import com.fasterxml.jackson.annotation.JsonProperty;
import com.resolveflow.caseservice.casefile.CaseCreateRequest;
import com.resolveflow.caseservice.casefile.CaseService;
import com.resolveflow.caseservice.casefile.CaseWriter;
import com.resolveflow.caseservice.casefile.CustomerCaseRepository;
import com.resolveflow.caseservice.casefile.CustomerCaseService;
import com.resolveflow.caseservice.casefile.EvidenceRepository;
import com.resolveflow.caseservice.order.RequestPrincipalResolver.Session;
import com.resolveflow.shared.contract.CanonicalJson;
import com.resolveflow.shared.security.AuthenticatedPrincipal;
import com.resolveflow.shared.security.Role;
import com.resolveflow.shared.support.SupportRefundWire.*;
import java.time.Clock;
import java.time.Instant;
import java.util.UUID;
import java.util.function.Supplier;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Service;
import org.springframework.transaction.PlatformTransactionManager;
import org.springframework.transaction.TransactionDefinition;
import org.springframework.transaction.support.TransactionTemplate;
import tools.jackson.databind.ObjectMapper;

/** Drafts are local business state, completely separate from model generation views. */
@Service
public class SupportRefundService {
    public record View(Draft draft, CustomerCaseService.Detail application) {}

    private record Conversation(String id, String merchant, String customer, String line, long version) {}

    private final JdbcTemplate db;
    private final CustomerCaseService customerCases;
    private final CustomerCaseRepository lists;
    private final ObjectMapper json;
    private final Clock clock;
    private final TransactionTemplate tx;
    private final CaseService cases;
    private final CaseWriter writer;
    private final EvidenceRepository evidence;

    public SupportRefundService(
            JdbcTemplate db,
            CustomerCaseService customerCases,
            CustomerCaseRepository lists,
            ObjectMapper json,
            Clock clock,
            PlatformTransactionManager transactions,
            CaseService cases,
            CaseWriter writer,
            EvidenceRepository evidence) {
        this.db = db;
        this.customerCases = customerCases;
        this.lists = lists;
        this.json = json;
        this.clock = clock;
        this.tx = new TransactionTemplate(transactions);
        this.tx.setIsolationLevel(TransactionDefinition.ISOLATION_READ_COMMITTED);
        this.cases = cases;
        this.writer = writer;
        this.evidence = evidence;
    }

    private static SupportService.Refused refused(int status, String text) {
        return new SupportService.Refused(
                status,
                status == 404
                        ? "NOT_FOUND"
                        : status == 400 ? "INVALID_ARGUMENT" : status == 403 ? "FORBIDDEN_SCOPE" : "STATE_CONFLICT",
                text);
    }

    private static void reason(String text) {
        if (text == null || text.isBlank() || text.length() > 4000) throw refused(400, "请填写不超过4000字的申请原因");
    }

    private Conversation conversation(Session s, String id, boolean lock) {
        if (!s.principal().isPlatformBuyer()) throw refused(403, "请使用平台买家账号");
        if (lock) {
            var p = s.principal();
            if (db.queryForList(
                            "SELECT username FROM identity_account WHERE username=? AND enabled=TRUE AND identity_version=? AND role='CUSTOMER' AND buyer_id=? FOR UPDATE",
                            p.subject(),
                            s.identityVersion(),
                            p.buyerId())
                    .isEmpty()) throw new SupportService.Refused(401, "UNAUTHENTICATED", "登录状态已变化，请重新登录");
        }
        var rows = db.query(
                "SELECT * FROM support_conversation WHERE conversation_id=? AND buyer_id=?"
                        + (lock ? " FOR UPDATE" : ""),
                (rs, n) -> new Conversation(
                        rs.getString("conversation_id"),
                        rs.getString("merchant_id"),
                        rs.getString("customer_id"),
                        rs.getString("line_id"),
                        rs.getLong("version")),
                id,
                s.principal().buyerId());
        if (rows.isEmpty()) throw refused(404, "咨询记录不存在");
        var c = rows.getFirst();
        if (db.queryForList(
                        "SELECT b.buyer_id FROM buyer_customer_binding b JOIN identity_merchant m ON m.merchant_id=b.merchant_id WHERE b.buyer_id=? AND b.merchant_id=? AND b.customer_id=? AND m.enabled=TRUE"
                                + (lock ? " FOR SHARE" : ""),
                        s.principal().buyerId(),
                        c.merchant(),
                        c.customer())
                .isEmpty()) throw refused(404, "咨询记录不存在");
        return c;
    }

    private AuthenticatedPrincipal scope(Session s, Conversation c) {
        return new AuthenticatedPrincipal(s.principal().subject(), c.merchant(), Role.CUSTOMER, c.customer());
    }

    private Draft draft(Conversation c) {
        var rows = db.query(
                "SELECT * FROM support_refund_draft WHERE conversation_id=?",
                (rs, n) -> {
                    String state = rs.getString("status");
                    Instant expiry = rs.getTimestamp("expires_at").toInstant();
                    if (state.equals("DRAFT"))
                        state = !expiry.isAfter(clock.instant())
                                ? "EXPIRED"
                                : rs.getLong("input_version") != c.version() ? "STALE" : state;
                    return new Draft(
                            rs.getString("draft_id"),
                            rs.getLong("revision"),
                            rs.getLong("input_version"),
                            state,
                            rs.getString("reason"),
                            rs.getInt("quantity"),
                            rs.getLong("amount_minor"),
                            rs.getString("currency"),
                            expiry,
                            rs.getString("case_id"));
                },
                c.id());
        return rows.isEmpty() ? null : rows.getFirst();
    }

    private View view(Session s, Conversation c) {
        var related = lists.related(c.merchant(), c.customer(), c.line());
        return new View(draft(c), related == null ? null : customerCases.read(scope(s, c), related.caseId()));
    }

    public View read(Session s, String id) {
        return tx.execute(status -> view(s, conversation(s, id, false)));
    }

    private void version(Conversation c, Long expected) {
        if (expected == null || expected < 1) throw refused(400, "请提供当前会话版本");
        if (expected != c.version()) throw refused(409, "咨询已更新，请重新核对申请摘要");
    }

    private Draft editable(Conversation c, String id, Long revision) {
        var d = draft(c);
        if (revision == null || revision < 1) throw refused(400, "请提供当前摘要版本");
        if (d == null
                || !d.draftId().equals(id)
                || d.revision() != revision
                || !d.status().equals("DRAFT")) throw refused(409, "申请摘要已变化或过期，请重新核对");
        return d;
    }

    private View replay(Conversation c, Session s, String key, String operation, Object body) {
        var rows = db.queryForList(
                "SELECT request_json,response_json FROM support_receipt WHERE conversation_id=? AND actor=? AND operation=? AND request_key=?",
                c.id(),
                s.principal().subject(),
                operation,
                key);
        if (rows.isEmpty()) return null;
        if (!json.readTree(rows.getFirst().get("request_json").toString())
                .equals(json.readTree(json.writeValueAsString(body)))) throw refused(409, "同一请求标识对应的内容不一致");
        return json.readValue(rows.getFirst().get("response_json").toString(), View.class);
    }

    private View receipt(Conversation c, Session s, String key, String operation, Object body, Supplier<View> action) {
        var previous = replay(c, s, key, operation, body);
        if (previous != null) return previous;
        var result = action.get();
        db.update(
                "INSERT INTO support_receipt(conversation_id,actor,operation,request_key,request_json,response_json) VALUES(?,?,?,?,?,?)",
                c.id(),
                s.principal().subject(),
                operation,
                key,
                json.writeValueAsString(body),
                json.writeValueAsString(result));
        return result;
    }

    private static void key(String key) {
        if (key == null || !key.matches("[A-Za-z0-9_-]{1,128}")) throw refused(400, "请提供请求标识");
    }

    public View prepare(Session s, String id, String key, Prepare body) {
        key(key);
        reason(body.reason());
        var c = conversation(s, id, false);
        var previous = replay(c, s, key, "R_DRAFT", body);
        if (previous != null) return previous;
        version(c, body.expectedVersion());
        // Commerce is contacted before acquiring any local write locks.
        var line = customerCases.line(scope(s, c), c.line());
        return tx.execute(status -> {
            var current = conversation(s, id, true);
            return receipt(current, s, key, "R_DRAFT", body, () -> {
                version(current, body.expectedVersion());
                var related = lists.related(current.merchant(), current.customer(), current.line());
                if (related != null
                        && (!related.status().isTerminal()
                                || related.status() == com.resolveflow.caseservice.casefile.CaseStatus.CLOSED_SUCCESS))
                    return view(s, current);
                if (!line.canApply()) throw refused(409, line.blockedReason());
                // A second tab preparing the same conversation must preserve the customer's saved edits.
                var currentDraft = draft(current);
                if (currentDraft != null && currentDraft.status().equals("DRAFT")) return view(s, current);
                var l = line.orderLine();
                db.update(
                        "INSERT INTO support_refund_draft(conversation_id,draft_id,revision,input_version,status,reason,quantity,amount_minor,currency,expires_at) VALUES(?,?,1,?,'DRAFT',?,?,?,?,?) ON DUPLICATE KEY UPDATE draft_id=VALUES(draft_id),revision=1,input_version=VALUES(input_version),status='DRAFT',reason=VALUES(reason),quantity=VALUES(quantity),amount_minor=VALUES(amount_minor),currency=VALUES(currency),expires_at=VALUES(expires_at),case_id=NULL",
                        id,
                        UUID.randomUUID().toString(),
                        current.version(),
                        body.reason().trim(),
                        l.quantity(),
                        l.linePaidAmount(),
                        l.currency(),
                        java.sql.Timestamp.from(clock.instant().plusSeconds(1800)));
                return view(s, current);
            });
        });
    }

    public View edit(Session s, String id, String draftId, String key, Edit body) {
        key(key);
        reason(body.reason());
        return tx.execute(status -> {
            var c = conversation(s, id, true);
            return receipt(c, s, key, "R_EDIT", new Mutation(draftId, body), () -> {
                editable(c, draftId, body.revision());
                db.update(
                        "UPDATE support_refund_draft SET reason=?,revision=revision+1 WHERE conversation_id=?",
                        body.reason().trim(),
                        id);
                return view(s, c);
            });
        });
    }

    public View cancel(Session s, String id, String draftId, String key, Revision body) {
        key(key);
        return tx.execute(status -> {
            var c = conversation(s, id, true);
            return receipt(c, s, key, "R_CANCEL", new Mutation(draftId, body), () -> {
                editable(c, draftId, body.revision());
                db.update(
                        "UPDATE support_refund_draft SET status='CANCELLED',revision=revision+1 WHERE conversation_id=?",
                        id);
                return view(s, c);
            });
        });
    }

    private record Mutation(@JsonProperty("draft_id") String draftId, Object body) {}

    public View confirm(Session s, String id, String draftId, String key, Confirm body) {
        key(key);
        var c = conversation(s, id, false);
        var request = new Mutation(draftId, body);
        var previous = replay(c, s, key, "R_CONFIRM", request);
        if (previous != null) return previous;
        var d = draft(c);
        if (d != null
                && d.status().equals("CONFIRMED")
                && d.draftId().equals(draftId)
                && body.revision() != null
                && body.revision() == d.revision()
                && body.expectedVersion() != null
                && body.expectedVersion() == d.expectedVersion()) {
            return tx.execute(status -> {
                var current = conversation(s, id, true);
                return receipt(current, s, key, "R_CONFIRM", request, () -> {
                    var confirmed = draft(current);
                    if (confirmed == null
                            || !confirmed.status().equals("CONFIRMED")
                            || !confirmed.draftId().equals(draftId)
                            || confirmed.revision() != body.revision()
                            || confirmed.expectedVersion() != body.expectedVersion())
                        throw refused(409, "申请摘要已变化，请刷新当前申请");
                    return view(s, current);
                });
            });
        }
        version(c, body.expectedVersion());
        d = editable(c, draftId, body.revision());
        var p = scope(s, c);
        var line = customerCases.line(p, c.line());
        if (!line.canApply()) {
            if (line.application() != null
                    && (!line.application().status().isTerminal()
                            || line.application().status()
                                    == com.resolveflow.caseservice.casefile.CaseStatus.CLOSED_SUCCESS)) {
                return tx.execute(status -> {
                    var current = conversation(s, id, true);
                    return receipt(current, s, key, "R_CONFIRM", request, () -> {
                        version(current, body.expectedVersion());
                        editable(current, draftId, body.revision());
                        return view(s, current);
                    });
                });
            }
            throw refused(409, line.blockedReason());
        }
        if (line.orderLine().linePaidAmount() != d.amountMinor()
                || line.orderLine().quantity() != d.quantity()
                || !line.orderLine().currency().equals(d.currency())) throw refused(409, "订单金额已变化，请重新核对申请摘要");
        var prepared = cases.prepare(
                p,
                "support-refund:" + draftId,
                new CaseCreateRequest(c.line(), d.reason(), java.util.List.of("REFUND")));
        try {
            return tx.execute(status -> {
                var current = conversation(s, id, true);
                return receipt(current, s, key, "R_CONFIRM", request, () -> {
                    version(current, body.expectedVersion());
                    var confirmedReason = editable(current, draftId, body.revision());
                    var existing = lists.related(current.merchant(), current.customer(), current.line());
                    if (existing != null
                            && (!existing.status().isTerminal()
                                    || existing.status()
                                            == com.resolveflow.caseservice.casefile.CaseStatus.CLOSED_SUCCESS))
                        return view(s, current);
                    var created =
                            prepared.replayed() != null ? prepared.replayed() : writer.writeCase(prepared.write());
                    if (prepared.replayed() == null) {
                        registerConfirmedReason(
                                s, current, confirmedReason, created.body().caseId());
                    }
                    db.update(
                            "UPDATE support_refund_draft SET status='CONFIRMED',case_id=? WHERE conversation_id=?",
                            created.body().caseId(),
                            id);
                    return view(s, current);
                });
            });
        } catch (org.springframework.dao.DuplicateKeyException error) {
            // An old /cases request can win the line slot concurrently; never create a replacement.
            var current = read(s, id);
            if (current.application() != null) {
                return tx.execute(status -> {
                    var locked = conversation(s, id, true);
                    return receipt(locked, s, key, "R_CONFIRM", request, () -> view(s, locked));
                });
            }
            throw refused(409, "申请状态已变化，请刷新后重试同一请求");
        }
    }

    /** Initial customer input, committed with the new case, not a later append or a verification. */
    private void registerConfirmedReason(Session s, Conversation c, Draft d, String caseId) {
        var provenance = json.createObjectNode();
        provenance.put("case_id", caseId);
        provenance.put("conversation_id", c.id());
        provenance.put("conversation_version", c.version());
        provenance.put("draft_id", d.draftId());
        provenance.put("draft_revision", d.revision());
        provenance.put("evidence_kind", "CUSTOMER_STATEMENT");
        provenance.put("text", d.reason());
        provenance.put("submitted_by", s.principal().subject());
        provenance.put("submitted_role", "CUSTOMER");
        Instant now = Instant.now(clock);
        evidence.insertEvidence(
                caseId,
                UUID.randomUUID().toString(),
                "CUSTOMER_STATEMENT",
                "customer:" + c.customer() + ":support-refund:" + c.id() + ":" + d.draftId(),
                "conversation-" + c.version() + ":draft-" + d.revision(),
                CanonicalJson.contentHash(provenance),
                1,
                now,
                d.reason(),
                null,
                null,
                null,
                s.principal().subject(),
                "CUSTOMER",
                now);
    }
}
