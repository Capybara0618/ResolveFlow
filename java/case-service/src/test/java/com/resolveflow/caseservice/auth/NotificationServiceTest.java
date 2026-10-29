package com.resolveflow.caseservice.auth;

import static org.assertj.core.api.Assertions.*;

import com.resolveflow.caseservice.CaseDatabaseTest;
import com.resolveflow.caseservice.order.RequestPrincipalResolver.Session;
import com.resolveflow.caseservice.shopping.CommerceShoppingClient.Refused;
import com.resolveflow.shared.security.AuthenticatedPrincipal;
import com.resolveflow.shared.security.Role;
import java.util.UUID;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;

class NotificationServiceTest extends CaseDatabaseTest {
    @Autowired
    NotificationService service;

    Session buyer() {
        return new Session(
                new AuthenticatedPrincipal("demo-buyer", null, Role.CUSTOMER, null, "B-3001"),
                jdbc.queryForObject(
                        "SELECT identity_version FROM identity_account WHERE username='demo-buyer'", Long.class));
    }

    Session merchant(String id) {
        return new Session(
                new AuthenticatedPrincipal("demo-admin", id, Role.MERCHANT_ADMIN, null),
                jdbc.queryForObject(
                        "SELECT identity_version FROM identity_account WHERE username='demo-admin'", Long.class));
    }

    String conversation() {
        String id = UUID.randomUUID().toString();
        jdbc.update(
                "INSERT INTO support_conversation(conversation_id,buyer_id,merchant_id,customer_id,order_id,line_id,store_name,product_json) VALUES(?,'B-3001','M-1001','C-B3001-M1001',?,?, '测试店铺','{}')",
                id,
                UUID.randomUUID().toString(),
                UUID.randomUUID().toString());
        return id;
    }

    String message(String conv, String author, String recipient, String ticket) {
        String id = UUID.randomUUID().toString();
        long sequence =
                jdbc.queryForObject("SELECT COUNT(*)+1 FROM support_message WHERE conversation_id=?", Long.class, conv);
        jdbc.update(
                "INSERT INTO support_message(message_id,conversation_id,sequence,author,recipient,actor,text,ticket_id) VALUES(?,?,?,?,?,'demo-buyer','私人内容不可出现在提醒中',?)",
                id,
                conv,
                sequence,
                author,
                recipient,
                ticket);
        return "message:" + id;
    }

    @Test
    void projectsOnlyVisibleBusinessEventsAndPersistsReadStateWithoutDuplicatingEvents() {
        var c = conversation();
        String ticket = UUID.randomUUID().toString();
        jdbc.update(
                "INSERT INTO support_ticket(ticket_id,conversation_id,merchant_id,status,summary,shared_json,created_at) VALUES(?,?,'M-1001','PENDING','核查','[]',CURRENT_TIMESTAMP(6))",
                ticket,
                c);
        String privateMessage = message(c, "CUSTOMER", "ASSISTANT", null);
        String reply = message(c, "MERCHANT", "CUSTOMER", ticket);
        String supplement = message(c, "CUSTOMER", "MERCHANT", ticket);
        var page = service.list(buyer(), null);
        assertThat(page.items())
                .extracting(NotificationService.Item::notification_id)
                .contains(reply)
                .doesNotContain(privateMessage, supplement, "ticket:" + ticket);
        assertThat(page.items().toString()).doesNotContain("私人内容");
        assertThat(service.list(merchant("M-1001"), null).items())
                .extracting(NotificationService.Item::notification_id)
                .contains(supplement, "ticket:" + ticket)
                .doesNotContain(privateMessage, reply);
        assertThat(service.list(merchant("M-1002"), null).items())
                .extracting(NotificationService.Item::notification_id)
                .doesNotContain(reply, supplement, "ticket:" + ticket);
        assertThatThrownBy(() -> service.read(merchant("M-1002"), reply)).isInstanceOf(Refused.class);
        long before = page.unread_count();
        service.read(buyer(), reply);
        service.read(buyer(), reply);
        assertThat(service.list(buyer(), null).unread_count()).isEqualTo(before - 1);
        assertThat(service.list(buyer(), null).items().stream()
                        .filter(i -> i.notification_id().equals(reply))
                        .findFirst()
                        .orElseThrow()
                        .read())
                .isTrue();
    }

    @Test
    void revokedIdentityCannotMarkReadAndCursorValidationIsExplicit() {
        assertThatThrownBy(() -> service.list(buyer(), "broken")).isInstanceOf(Refused.class);
        var s = buyer();
        var revoked = new Session(s.principal(), s.identityVersion() + 1);
        assertThatThrownBy(() -> service.read(revoked, "message:" + UUID.randomUUID()))
                .isInstanceOf(Refused.class);
    }

    @Autowired
    com.resolveflow.caseservice.casefile.CaseRepository cases;

    @Test
    void refundAndRequiredMaterialNoticesAreScopedAndDoNotExposeInternalDetails() {
        String id = UUID.randomUUID().toString(), event = UUID.randomUUID().toString();
        var now = java.time.Instant.now();
        cases.insertCase(
                id,
                "M-1001",
                "C-B3001-M1001",
                UUID.randomUUID().toString(),
                UUID.randomUUID().toString(),
                "测试申请",
                "CLOSED_SUCCESS",
                1,
                1,
                null,
                now,
                now);
        cases.insertTimeline(
                id,
                event,
                1,
                "CASE_CLOSED",
                "{\"outcome\":\"SUCCEEDED\",\"operation_id\":\"private-operation\"}",
                now,
                1);
        var result = service.list(buyer(), null).items().stream()
                .filter(n -> n.notification_id().equals("case:" + event))
                .findFirst()
                .orElseThrow();
        assertThat(result.title()).isEqualTo("模拟退款已完成");
        assertThat(result.target_id()).isEqualTo(id);
        assertThat(result.toString()).doesNotContain("private-operation");
        cases.insertTimeline(id, UUID.randomUUID().toString(), 2, "QUESTION_REQUIRED", "{}", now, 1);
        assertThat(service.list(buyer(), null).items())
                .extracting(NotificationService.Item::title)
                .contains("售后申请需要补充说明");
    }
}
