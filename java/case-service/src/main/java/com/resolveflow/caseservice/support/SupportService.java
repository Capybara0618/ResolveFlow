package com.resolveflow.caseservice.support;

import com.resolveflow.caseservice.auth.BuyerScopes;
import com.resolveflow.caseservice.order.CommerceOrderLineClient;
import com.resolveflow.caseservice.order.RequestPrincipalResolver.Session;
import com.resolveflow.shared.security.Role;
import com.resolveflow.shared.support.SupportWire.*;
import java.sql.ResultSet;
import java.sql.SQLException;
import java.util.*;
import java.util.function.Supplier;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Service;
import org.springframework.transaction.PlatformTransactionManager;
import org.springframework.transaction.TransactionDefinition;
import org.springframework.transaction.support.TransactionTemplate;
import tools.jackson.databind.ObjectMapper;

@Service
public class SupportService {
    public static class Refused extends RuntimeException {
        public final int status;
        public final String code;

        public Refused(int status, String code, String message) {
            super(message);
            this.status = status;
            this.code = code;
        }
    }

    private final JdbcTemplate db;
    private final TransactionTemplate tx;
    private final TransactionTemplate writes;
    private final BuyerScopes buyers;
    private final CommerceOrderLineClient commerce;
    private final ObjectMapper json;
    private final SupportAgentTurns turns;

    public SupportService(
            JdbcTemplate db,
            PlatformTransactionManager transactions,
            BuyerScopes buyers,
            CommerceOrderLineClient commerce,
            ObjectMapper json,
            SupportAgentTurns turns) {
        this.db = db;
        this.tx = new TransactionTemplate(transactions);
        this.buyers = buyers;
        this.commerce = commerce;
        this.json = json;
        this.turns = turns;
        this.writes = new TransactionTemplate(transactions);
        this.writes.setIsolationLevel(TransactionDefinition.ISOLATION_READ_COMMITTED);
    }

    private static Refused invalid() {
        return new Refused(400, "INVALID_ARGUMENT", "请检查文本、版本和请求标识");
    }

    private static Refused missing() {
        return new Refused(404, "NOT_FOUND", "咨询记录不存在");
    }

    private static Refused conflict(String message) {
        return new Refused(409, "STATE_CONFLICT", message);
    }

    private static void text(String value, int max) {
        if (value == null || value.isBlank() || value.length() > max) throw invalid();
    }

    private static void buyer(Session s) {
        if (!s.principal().isPlatformBuyer()) throw new Refused(403, "FORBIDDEN_SCOPE", "请使用平台买家账号");
    }

    private static void merchant(Session s) {
        if (s.principal().role() != Role.MERCHANT_ADMIN) throw new Refused(403, "FORBIDDEN_SCOPE", "请使用本店商家账号");
    }

    private static String uuid() {
        return UUID.randomUUID().toString();
    }

    /** Account lock fences disable/password/role races; no Commerce call occurs in this transaction. */
    private void actor(Session s) {
        var p = s.principal();
        var rows = db.queryForList(
                "SELECT username FROM identity_account WHERE username=? AND enabled=TRUE AND identity_version=? AND role=? AND buyer_id <=> ? AND merchant_id <=> ? AND customer_id <=> ? FOR UPDATE",
                String.class,
                p.subject(),
                s.identityVersion(),
                p.role().name(),
                p.buyerId(),
                p.merchantId(),
                p.customerId());
        if (rows.isEmpty()) throw new Refused(401, "UNAUTHENTICATED", "登录状态已变化，请重新登录");
    }

    private void binding(Row r) {
        var stores = db.queryForList(
                "SELECT merchant_id FROM identity_merchant WHERE merchant_id=? AND enabled=TRUE FOR SHARE",
                String.class,
                r.merchant);
        var bindings = db.queryForList(
                "SELECT buyer_id FROM buyer_customer_binding WHERE buyer_id=? AND merchant_id=? AND customer_id=? FOR SHARE",
                String.class,
                r.buyer,
                r.merchant,
                r.customer);
        if (stores.isEmpty() || bindings.isEmpty()) throw missing();
    }

    private record Row(
            String id,
            long sort,
            String buyer,
            String merchant,
            String customer,
            String order,
            String line,
            String store,
            Product product,
            long version) {}

    private Row row(ResultSet rs, int n) throws SQLException {
        return new Row(
                rs.getString("conversation_id"),
                rs.getLong("sort_id"),
                rs.getString("buyer_id"),
                rs.getString("merchant_id"),
                rs.getString("customer_id"),
                rs.getString("order_id"),
                rs.getString("line_id"),
                rs.getString("store_name"),
                json.readValue(rs.getString("product_json"), Product.class),
                rs.getLong("version"));
    }

    private Row find(Session s, String id, boolean staff, boolean lock) {
        if (staff) merchant(s);
        else buyer(s);
        var rows = db.query(
                "SELECT * FROM support_conversation WHERE conversation_id=? AND " + (staff ? "merchant_id" : "buyer_id")
                        + "=?" + (lock ? " FOR UPDATE" : ""),
                this::row,
                id,
                staff ? s.principal().merchantId() : s.principal().buyerId());
        if (rows.isEmpty()) throw missing();
        return rows.getFirst();
    }

    private Ticket ticket(Row r) {
        var rows = db.query(
                "SELECT * FROM support_ticket WHERE conversation_id=?",
                (rs, n) -> new Ticket(
                        rs.getString("ticket_id"),
                        rs.getString("status"),
                        rs.getString("summary"),
                        List.of(json.readValue(rs.getString("shared_json"), Message[].class)),
                        rs.getString("report_json") == null
                                ? null
                                : json.readValue(rs.getString("report_json"), Assistant.class)),
                r.id);
        return rows.isEmpty() ? null : rows.getFirst();
    }

    private Message message(ResultSet rs, int n) throws SQLException {
        return new Message(
                rs.getString("message_id"),
                rs.getLong("sequence"),
                rs.getString("author"),
                rs.getString("recipient"),
                rs.getString("text"),
                rs.getString("ticket_id"),
                rs.getTimestamp("created_at").toInstant(),
                rs.getString("assistant_json") == null
                        ? null
                        : json.readValue(rs.getString("assistant_json"), Assistant.class));
    }

    private record Messages(List<Message> items, Long next) {}

    private Messages messages(Row r, boolean staff, Long before) {
        if (before != null && before < 1) throw invalid();
        var items = new ArrayList<>(db.query(
                "SELECT * FROM support_message WHERE conversation_id=? AND sequence<?"
                        + (staff ? " AND ticket_id IS NOT NULL" : "") + " ORDER BY sequence DESC LIMIT 51",
                this::message,
                r.id,
                before == null ? Long.MAX_VALUE : before));
        boolean more = items.size() > 50;
        if (more) items.removeLast();
        Long next = more ? items.getLast().sequence() : null;
        Collections.reverse(items);
        return new Messages(items, next);
    }

    private Conversation detail(Row r, Long before) {
        var page = messages(r, false, before);
        return new Conversation(
                r.id,
                r.merchant,
                r.store,
                r.order,
                r.line,
                r.product,
                r.version,
                ticket(r),
                page.items,
                page.next,
                turns.view(r.id));
    }

    private TicketDetail staffDetail(Row r, Long before) {
        var page = messages(r, true, before);
        return new TicketDetail(
                r.id, r.merchant, r.store, r.order, r.line, r.product, r.version, ticket(r), page.items, page.next);
    }

    public Conversation open(Session s, Open body) {
        buyer(s);
        text(body.lineId(), 64);
        // Trusted scoped lookup, outside the local transaction. Never copy a caller's tenant id.
        var scope = buyers.forLine(s.principal(), body.lineId());
        var lines = commerce.listByLine(scope, body.lineId()).items();
        if (lines.size() != 1) throw missing();
        var line = lines.getFirst();
        String store = buyers.list(s.principal()).stream()
                .filter(b -> b.merchantId().equals(scope.merchantId()))
                .findFirst()
                .orElseThrow(SupportService::missing)
                .merchantName();
        var product = new Product(
                line.productName() == null ? line.sku() : line.productName(),
                line.variantText(),
                line.assetKey(),
                line.quantity(),
                line.linePaidAmount(),
                line.currency());
        return writes.execute(status -> {
            actor(s);
            var proposed = new Row(
                    uuid(),
                    0,
                    s.principal().buyerId(),
                    scope.merchantId(),
                    scope.customerId(),
                    line.orderId(),
                    line.lineId(),
                    store,
                    product,
                    1);
            binding(proposed);
            db.update(
                    "INSERT INTO support_conversation(conversation_id,buyer_id,merchant_id,customer_id,order_id,line_id,store_name,product_json) VALUES(?,?,?,?,?,?,?,?) ON DUPLICATE KEY UPDATE conversation_id=conversation_id",
                    proposed.id,
                    proposed.buyer,
                    proposed.merchant,
                    proposed.customer,
                    proposed.order,
                    proposed.line,
                    proposed.store,
                    json.writeValueAsString(product));
            var r = db.query(
                            "SELECT * FROM support_conversation WHERE buyer_id=? AND line_id=? FOR UPDATE",
                            this::row,
                            proposed.buyer,
                            proposed.line)
                    .getFirst();
            return detail(r, null);
        });
    }

    public Conversation read(Session s, String id, Long before) {
        return tx.execute(st -> detail(find(s, id, false, false), before));
    }

    private Row forTicket(Session s, String id, boolean lock) {
        merchant(s);
        var ids = db.queryForList(
                "SELECT conversation_id FROM support_ticket WHERE ticket_id=? AND merchant_id=?",
                String.class,
                id,
                s.principal().merchantId());
        if (ids.isEmpty()) throw missing();
        return find(s, ids.getFirst(), true, lock);
    }

    public TicketDetail readTicket(Session s, String id, Long before) {
        return tx.execute(st -> staffDetail(forTicket(s, id, false), before));
    }

    private static int limit(Integer n) {
        int v = n == null ? 20 : n;
        if (v < 1 || v > 50) throw invalid();
        return v;
    }

    public Page<Conversation> list(Session s, Integer n, Long before) {
        buyer(s);
        int size = limit(n);
        if (before != null && before < 1) throw invalid();
        return tx.execute(st -> {
            var rows = db.query(
                    "SELECT * FROM support_conversation WHERE buyer_id=? AND sort_id<? ORDER BY sort_id DESC LIMIT ?",
                    this::row,
                    s.principal().buyerId(),
                    before == null ? Long.MAX_VALUE : before,
                    size + 1);
            var items = rows.stream()
                    .limit(size)
                    .map(r -> new Conversation(
                            r.id,
                            r.merchant,
                            r.store,
                            r.order,
                            r.line,
                            r.product,
                            r.version,
                            ticket(r),
                            List.of(),
                            null))
                    .toList();
            return new Page<>(items, rows.size() > size ? rows.get(size - 1).sort : null);
        });
    }

    public Page<TicketDetail> tickets(Session s, Integer n, Long before) {
        merchant(s);
        int size = limit(n);
        if (before != null && before < 1) throw invalid();
        return tx.execute(st -> {
            var rows = db.query(
                    "SELECT c.* FROM support_conversation c JOIN support_ticket t ON c.conversation_id=t.conversation_id WHERE t.merchant_id=? AND t.sort_id<? ORDER BY t.sort_id DESC LIMIT ?",
                    this::row,
                    s.principal().merchantId(),
                    before == null ? Long.MAX_VALUE : before,
                    size + 1);
            var items = rows.stream()
                    .limit(size)
                    .map(r -> new TicketDetail(
                            r.id,
                            r.merchant,
                            r.store,
                            r.order,
                            r.line,
                            r.product,
                            r.version,
                            ticket(r),
                            List.of(),
                            null))
                    .toList();
            Long next = rows.size() > size
                    ? db.queryForObject(
                            "SELECT sort_id FROM support_ticket WHERE conversation_id=?",
                            Long.class,
                            rows.get(size - 1).id)
                    : null;
            return new Page<>(items, next);
        });
    }

    private <T> T write(
            Session s,
            String id,
            boolean staff,
            String operation,
            String key,
            Object request,
            Long expected,
            Class<T> type,
            Supplier<T> action) {
        if (key == null || !key.matches("[A-Za-z0-9_-]{1,128}") || expected == null || expected < 1) throw invalid();
        return writes.execute(st -> {
            actor(s);
            // Check store/binding before the conversation lock to keep the lock order uniform.
            Row visible = find(s, id, staff, false);
            binding(visible);
            Row r = find(s, id, staff, true);
            String encoded = json.writeValueAsString(request);
            var receipts = db.query(
                    "SELECT request_json,response_json FROM support_receipt WHERE conversation_id=? AND actor=? AND operation=? AND request_key=?",
                    (rs, n) -> new String[] {rs.getString(1), rs.getString(2)},
                    r.id,
                    s.principal().subject(),
                    operation,
                    key);
            if (!receipts.isEmpty()) {
                var saved = receipts.getFirst();
                if (!json.readTree(saved[0]).equals(json.readTree(encoded)))
                    throw new Refused(409, "IDEMPOTENCY_CONFLICT", "该请求标识已用于不同内容");
                return json.readValue(saved[1], type);
            }
            if (r.version != expected) throw conflict("咨询已更新，请刷新后重新确认");
            T result = action.get();
            db.update(
                    "INSERT INTO support_receipt(conversation_id,actor,operation,request_key,request_json,response_json) VALUES(?,?,?,?,?,?)",
                    r.id,
                    s.principal().subject(),
                    operation,
                    key,
                    encoded,
                    json.writeValueAsString(result));
            return result;
        });
    }

    private Row append(Row r, Session s, String author, String recipient, String text, String ticketId) {
        long next = r.version + 1;
        db.update(
                "INSERT INTO support_message(message_id,conversation_id,sequence,author,recipient,actor,text,ticket_id) VALUES(?,?,?,?,?,?,?,?)",
                uuid(),
                r.id,
                next,
                author,
                recipient,
                s.principal().subject(),
                text,
                ticketId);
        bump(r);
        return find(s, r.id, author.equals("MERCHANT"), true);
    }

    private void bump(Row r) {
        db.update("UPDATE support_conversation SET version=version+1 WHERE conversation_id=?", r.id);
        db.update(
                "UPDATE support_agent_turn SET status='STALE',reason='INPUT_CHANGED' WHERE conversation_id=? AND status IN ('PENDING','RUNNING')",
                r.id);
    }

    public Conversation send(Session s, String id, String key, Send body) {
        buyer(s);
        text(body.text(), 4000);
        if (!List.of("ASSISTANT", "MERCHANT").contains(body.recipient() == null ? "" : body.recipient()))
            throw invalid();
        return write(s, id, false, "SEND", key, body, body.expectedVersion(), Conversation.class, () -> {
            Row r = find(s, id, false, true);
            Ticket ticket = ticket(r);
            String tid = null;
            if (body.recipient().equals("MERCHANT")) {
                if (ticket == null) throw conflict("请先预览并确认转交商家");
                tid = ticket.ticketId();
                db.update("UPDATE support_ticket SET status='PENDING' WHERE ticket_id=?", tid);
            }
            var updated = append(r, s, "CUSTOMER", body.recipient(), body.text(), tid);
            if (body.recipient().equals("ASSISTANT")) turns.enqueue(s, id, updated.version);
            return detail(updated, null);
        });
    }

    public Conversation handoff(Session s, String id, String key, Handoff body) {
        buyer(s);
        text(body.summary(), 2000);
        if (body.sharedMessageIds() == null
                || body.sharedMessageIds().size() > 20
                || new HashSet<>(body.sharedMessageIds()).size()
                        != body.sharedMessageIds().size()) throw invalid();
        for (String mid : body.sharedMessageIds()) text(mid, 36);
        return write(s, id, false, "HANDOFF", key, body, body.expectedVersion(), Conversation.class, () -> {
            Row r = find(s, id, false, true);
            if (ticket(r) != null) throw new Refused(409, "TICKET_ALREADY_EXISTS", "请继续当前商家核查记录");
            var shared = new ArrayList<Message>();
            for (String mid : body.sharedMessageIds()) {
                var found = db.query(
                        "SELECT * FROM support_message WHERE conversation_id=? AND message_id=? AND author='CUSTOMER' AND recipient='ASSISTANT'",
                        this::message,
                        id,
                        mid);
                if (found.isEmpty()) throw invalid();
                shared.add(found.getFirst());
            }
            shared.sort(Comparator.comparingLong(Message::sequence));
            Assistant report = null;
            if (body.assistantMessageId() != null) {
                var entries = db.query(
                        "SELECT * FROM support_message WHERE conversation_id=? AND message_id=? AND author='ASSISTANT' AND sequence=?",
                        this::message,
                        id,
                        body.assistantMessageId(),
                        r.version);
                if (entries.isEmpty() || entries.getFirst().assistant() == null)
                    throw new Refused(409, "ASSISTANT_SUMMARY_STALE", "助手建议已过时，请重新核对或手工填写摘要");
                var value = entries.getFirst().assistant();
                report = new Assistant(
                        value.runId(),
                        value.mode(),
                        value.citations().stream()
                                .filter(c ->
                                        List.of("ORDER", "SHIPMENT", "POLICY").contains(c.get("source_type")))
                                .toList(),
                        value.handoffSummary());
            }
            db.update(
                    "INSERT INTO support_ticket(ticket_id,conversation_id,merchant_id,status,summary,shared_json) VALUES(?,?,?,'PENDING',?,?)",
                    uuid(),
                    id,
                    r.merchant,
                    body.summary(),
                    json.writeValueAsString(shared));
            if (report != null)
                db.update(
                        "UPDATE support_ticket SET report_json=? WHERE conversation_id=?",
                        json.writeValueAsString(report),
                        id);
            bump(r);
            return detail(find(s, id, false, true), null);
        });
    }

    public TicketDetail reply(Session s, String ticketId, String key, Reply body) {
        merchant(s);
        text(body.text(), 4000);
        if (!List.of("REPLY", "REQUEST_INFO").contains(body.kind() == null ? "" : body.kind())) throw invalid();
        Row visible = forTicket(s, ticketId, false);
        return write(s, visible.id, true, "REPLY", key, body, body.expectedVersion(), TicketDetail.class, () -> {
            Row r = find(s, visible.id, true, true);
            Ticket ticket = ticket(r);
            if (ticket.status().equals("RESOLVED")) throw conflict("客户已确认解决，等待客户重新补充后接续");
            db.update(
                    "UPDATE support_ticket SET status=? WHERE ticket_id=?",
                    body.kind().equals("REQUEST_INFO") ? "WAITING_CUSTOMER" : "REPLIED",
                    ticketId);
            return staffDetail(append(r, s, "MERCHANT", "CUSTOMER", body.text(), ticketId), null);
        });
    }

    public Conversation resolve(Session s, String id, String key, Resolve body) {
        buyer(s);
        return write(s, id, false, "RESOLVE", key, body, body.expectedVersion(), Conversation.class, () -> {
            Row r = find(s, id, false, true);
            Ticket t = ticket(r);
            if (t == null || !t.status().equals("REPLIED")) throw conflict("请先查看商家回复，再确认解决");
            db.update("UPDATE support_ticket SET status='RESOLVED' WHERE ticket_id=?", t.ticketId());
            bump(r);
            return detail(find(s, id, false, true), null);
        });
    }
}
