package com.resolveflow.caseservice.auth;

import com.resolveflow.caseservice.order.RequestPrincipalResolver.Session;
import com.resolveflow.caseservice.shopping.CommerceShoppingClient.Refused;
import com.resolveflow.shared.security.Role;
import java.nio.charset.StandardCharsets;
import java.sql.Timestamp;
import java.time.Instant;
import java.util.*;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Service;
import org.springframework.transaction.PlatformTransactionManager;
import org.springframework.transaction.support.TransactionTemplate;

/** Notifications are projections of committed domain records; reading never manufactures events. */
@Service
public class NotificationService {
    public record Item(
            String notification_id,
            String title,
            String target,
            String target_id,
            String conversation_id,
            Instant created_at,
            boolean read) {}

    public record Page(List<Item> items, long unread_count, String next_cursor) {}

    private record Query(String sql, List<Object> args) {}

    private final JdbcTemplate db;
    private final TransactionTemplate tx;

    public NotificationService(JdbcTemplate db, PlatformTransactionManager manager) {
        this.db = db;
        tx = new TransactionTemplate(manager);
    }

    private Query sources(Session s) {
        var p = s.principal();
        if (p.isPlatformBuyer()) return new Query("""
            SELECT CONCAT('message:',m.message_id) id,'商家回复了你的咨询' title,'SUPPORT' target,c.conversation_id target_id,c.conversation_id,m.created_at
            FROM support_message m JOIN support_conversation c ON c.conversation_id=m.conversation_id
            JOIN identity_merchant store ON store.merchant_id=c.merchant_id AND store.enabled=TRUE
            JOIN buyer_customer_binding binding ON binding.buyer_id=c.buyer_id AND binding.merchant_id=c.merchant_id AND binding.customer_id=c.customer_id
            WHERE c.buyer_id=? AND m.author='MERCHANT' AND m.recipient='CUSTOMER'
            UNION ALL
            SELECT CONCAT('case:',t.event_id),CASE WHEN t.kind='QUESTION_REQUIRED' THEN '售后申请需要补充说明'
              WHEN JSON_UNQUOTE(JSON_EXTRACT(t.detail,'$.outcome'))='SUCCEEDED' THEN '模拟退款已完成' ELSE '售后申请有处理结果' END,
              'APPLICATION',c.case_id,NULL,t.occurred_at
            FROM case_timeline t JOIN aftersale_case c ON c.case_id=t.case_id
            JOIN buyer_customer_binding b ON b.merchant_id=c.merchant_id AND b.customer_id=c.customer_id
            JOIN identity_merchant store ON store.merchant_id=b.merchant_id AND store.enabled=TRUE
            WHERE b.buyer_id=? AND t.kind IN ('QUESTION_REQUIRED','CASE_CLOSED')
              AND COALESCE(JSON_UNQUOTE(JSON_EXTRACT(t.detail,'$.ignored_as_stale')),'false')<>'true'
            """, List.of(p.buyerId(), p.buyerId()));
        if (p.role() == Role.MERCHANT_ADMIN)
            return new Query("""
            SELECT CONCAT('message:',m.message_id) id,'买家发来了补充消息' title,'TICKET' target,m.ticket_id target_id,c.conversation_id,m.created_at
            FROM support_message m JOIN support_conversation c ON c.conversation_id=m.conversation_id
            WHERE c.merchant_id=? AND m.author='CUSTOMER' AND m.recipient='MERCHANT' AND m.ticket_id IS NOT NULL
            UNION ALL
            SELECT CONCAT('ticket:',t.ticket_id),'有新的咨询需要核查','TICKET',t.ticket_id,t.conversation_id,t.created_at
            FROM support_ticket t WHERE t.merchant_id=? AND t.created_at IS NOT NULL
            UNION ALL
            SELECT CONCAT('case:',t.event_id),'有售后申请需要处理','CASE',c.case_id,NULL,t.occurred_at
            FROM case_timeline t JOIN aftersale_case c ON c.case_id=t.case_id
            WHERE c.merchant_id=? AND t.kind IN ('APPROVAL_REQUIRED','AGENT_FAILED')
            """, List.of(p.merchantId(), p.merchantId(), p.merchantId()));
        throw new Refused(403, "FORBIDDEN_SCOPE", "此账号没有购物消息");
    }

    @org.springframework.transaction.annotation.Transactional(
            readOnly = true,
            isolation = org.springframework.transaction.annotation.Isolation.REPEATABLE_READ)
    public Page list(Session s, String cursor) {
        var source = sources(s);
        var args = new ArrayList<>(source.args());
        args.add(s.principal().subject());
        String joined = " FROM (" + source.sql()
                + ") n LEFT JOIN account_notification_read r ON r.notification_id=n.id AND r.username=?";
        long unread = db.queryForObject(
                "SELECT COUNT(*)" + joined + " WHERE r.notification_id IS NULL", Long.class, args.toArray());
        String filter = "";
        if (cursor != null) {
            try {
                if (cursor.length() > 512) throw new IllegalArgumentException();
                var parts = new String(Base64.getUrlDecoder().decode(cursor), StandardCharsets.UTF_8).split("\\n", -1);
                if (parts.length != 2 || !parts[1].matches("(message|ticket|case):[a-fA-F0-9-]{36}"))
                    throw new IllegalArgumentException();
                var at = Timestamp.from(Instant.parse(parts[0]));
                filter = " WHERE (n.created_at<? OR (n.created_at=? AND n.id<?))";
                args.add(at);
                args.add(at);
                args.add(parts[1]);
            } catch (RuntimeException e) {
                throw new Refused(400, "INVALID_ARGUMENT", "消息分页标识无效");
            }
        }
        var items = db.query(
                "SELECT n.*,r.notification_id IS NOT NULL AS is_read" + joined + filter
                        + " ORDER BY n.created_at DESC,n.id DESC LIMIT 25",
                (r, n) -> new Item(
                        r.getString("id"),
                        r.getString("title"),
                        r.getString("target"),
                        r.getString("target_id"),
                        r.getString("conversation_id"),
                        r.getTimestamp("created_at").toInstant(),
                        r.getBoolean("is_read")),
                args.toArray());
        String next = null;
        if (items.size() > 24) {
            var last = items.get(23);
            next = Base64.getUrlEncoder()
                    .withoutPadding()
                    .encodeToString(
                            (last.created_at() + "\n" + last.notification_id()).getBytes(StandardCharsets.UTF_8));
        }
        return new Page(items.stream().limit(24).toList(), unread, next);
    }

    public void read(Session s, String id) {
        var source = sources(s);
        tx.executeWithoutResult(st -> {
            var current = db.queryForList(
                    "SELECT username FROM identity_account WHERE username=? AND enabled=TRUE AND identity_version=? FOR UPDATE",
                    String.class,
                    s.principal().subject(),
                    s.identityVersion());
            if (current.isEmpty()) throw new Refused(401, "UNAUTHENTICATED", "登录已失效，请重新登录");
            var args = new ArrayList<>(source.args());
            args.add(id);
            if (db.queryForObject(
                            "SELECT COUNT(*) FROM (" + source.sql() + ") n WHERE n.id=?", Integer.class, args.toArray())
                    != 1) throw new Refused(404, "NOT_FOUND", "消息不存在");
            db.update(
                    "INSERT IGNORE INTO account_notification_read(username,notification_id) VALUES(?,?)",
                    s.principal().subject(),
                    id);
        });
    }
}
