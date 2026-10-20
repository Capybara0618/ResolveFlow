package com.resolveflow.caseservice.support;

import static org.assertj.core.api.Assertions.*;
import static org.mockito.ArgumentMatchers.*;
import static org.mockito.Mockito.*;

import com.resolveflow.caseservice.CaseDatabaseTest;
import com.resolveflow.caseservice.order.CommerceOrderLineClient;
import com.resolveflow.shared.security.AuthenticatedPrincipal;
import java.time.Instant;
import java.util.List;
import java.util.Map;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.resttestclient.autoconfigure.AutoConfigureRestTestClient;
import org.springframework.boot.test.context.TestConfiguration;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Primary;
import org.springframework.http.MediaType;
import org.springframework.test.web.servlet.client.RestTestClient;
import tools.jackson.databind.JsonNode;
import tools.jackson.databind.ObjectMapper;

/** Real isolated MySQL and HTTP; Commerce is a scoped stub, no model requests. */
@AutoConfigureRestTestClient
class SupportApiTest extends CaseDatabaseTest {
    @Autowired
    RestTestClient rest;

    @Autowired
    CommerceOrderLineClient commerce;

    @Autowired
    SupportService support;

    @Autowired
    com.resolveflow.caseservice.order.RequestPrincipalResolver principals;

    final ObjectMapper json = new ObjectMapper();
    String buyer, merchant, otherMerchant, otherBuyer;

    @TestConfiguration
    static class Configuration {
        @Bean
        @Primary
        CommerceOrderLineClient supportCommerce() {
            return mock(CommerceOrderLineClient.class);
        }
    }

    @BeforeEach
    void prepare() {
        // Only this new module's rows in the disposable test container.
        for (String t : List.of("support_receipt", "support_message", "support_ticket", "support_conversation"))
            jdbc.update("DELETE FROM " + t);
        jdbc.update("INSERT IGNORE INTO platform_buyer(buyer_id) VALUES ('B-support-other')");
        jdbc.update("""
            INSERT IGNORE INTO identity_account(username,role,buyer_id,display_name,password_hash)
            SELECT 'support-other','CUSTOMER','B-support-other','Other',password_hash
            FROM identity_account WHERE username='demo-buyer'
            """);
        reset(commerce);
        when(commerce.listByLine(any(), anyString())).thenAnswer(i -> {
            AuthenticatedPrincipal p = i.getArgument(0);
            String id = i.getArgument(1);
            boolean visible = (id.equals("support-A")
                            && p.merchantId().equals("M-1001")
                            && p.customerId().equals("C-B3001-M1001"))
                    || (id.equals("support-B")
                            && p.merchantId().equals("M-1002")
                            && p.customerId().equals("C-B3001-M1002"));
            return new CommerceOrderLineClient.OrderLinePage(
                    visible
                            ? List.of(new CommerceOrderLineClient.OrderLineSummary(
                                    "order-" + id,
                                    id,
                                    "SKU",
                                    "合成商品",
                                    "黑色",
                                    "electronics",
                                    1,
                                    32900,
                                    "CNY",
                                    Instant.parse("2026-09-20T08:00:00Z"),
                                    "PAID",
                                    1))
                            : List.of(),
                    null);
        });
        buyer = login("demo-buyer", "demo-pass-4001");
        merchant = login("demo-admin", "demo-pass-1100");
        otherMerchant = login("demo-admin-m2", "demo-pass-2100");
        otherBuyer = login("support-other", "demo-pass-4001");
    }

    String login(String user, String pass) {
        return "Bearer "
                + postRaw("/api/v1/auth/login", null, null, Map.of("username", user, "password", pass), 200)
                        .get("access_token")
                        .asString();
    }

    JsonNode postRaw(String path, String auth, String key, Object body, int status) {
        var req = rest.post().uri(path).contentType(MediaType.APPLICATION_JSON);
        if (auth != null) req.header("Authorization", auth);
        if (key != null) req.header("Idempotency-Key", key);
        var text = req.body(body)
                .exchange()
                .expectStatus()
                .isEqualTo(status)
                .expectBody(String.class)
                .returnResult()
                .getResponseBody();
        return json.readTree(text);
    }

    JsonNode post(String path, String auth, String key, Object body, int status) {
        return postRaw("/api/v1/support" + path, auth, key, body, status);
    }

    JsonNode get(String path, String auth, int status) {
        var req = rest.get().uri("/api/v1/support" + path);
        if (auth != null) req.header("Authorization", auth);
        return json.readTree(req.exchange()
                .expectStatus()
                .isEqualTo(status)
                .expectBody(String.class)
                .returnResult()
                .getResponseBody());
    }

    JsonNode open(String line) {
        return post("/conversations", buyer, null, Map.of("line_id", line), 200);
    }

    String path(JsonNode c) {
        return "/conversations/" + c.get("conversation_id").asString();
    }

    JsonNode message(JsonNode c, String key, String text, String to) {
        return post(
                path(c) + "/messages",
                buyer,
                key,
                Map.of("expected_version", c.get("version").asLong(), "text", text, "recipient", to),
                200);
    }

    long count(String table) {
        return jdbc.queryForObject("SELECT COUNT(*) FROM " + table, Long.class);
    }

    @Test
    void requiresOwnershipAndResumesOneConversationPerLine() {
        post("/conversations", null, null, Map.of("line_id", "support-A"), 401);
        post("/conversations", merchant, null, Map.of("line_id", "support-A"), 403);
        post("/conversations", otherBuyer, null, Map.of("line_id", "support-A"), 404);
        var a = open("support-A");
        assertThat(open("support-A").get("conversation_id")).isEqualTo(a.get("conversation_id"));
        var b = open("support-B");
        assertThat(b.get("merchant_id").asString()).isEqualTo("M-1002");
        get(path(a), otherBuyer, 404);
        get(path(a), merchant, 403);
        assertThat(get("/conversations", buyer, 200).get("items").size()).isEqualTo(2);
        assertThat(count("support_conversation")).isEqualTo(2);
    }

    @Test
    void handoffCopiesOnlySelectedOriginalsAndRepliesReachSameConversationWithoutRefund() {
        long cases = count("aftersale_case"), auths = count("case_authorization"), slots = count("active_case_slot");
        var c = message(open("support-A"), "private-1", "私密草稿，不给商家", "ASSISTANT");
        c = message(c, "private-2", "显示签收但我未收到，只想核查", "ASSISTANT");
        String shared = c.get("messages").get(1).get("message_id").asString();
        c = post(
                path(c) + "/tickets",
                buyer,
                "transfer",
                Map.of(
                        "expected_version",
                        c.get("version").asLong(),
                        "summary",
                        "只核查签收，不申请退款",
                        "shared_message_ids",
                        List.of(shared)),
                200);
        String ticket = c.get("ticket").get("ticket_id").asString();
        var detail = get("/tickets/" + ticket, merchant, 200);
        assertThat(detail.toString()).contains("显示签收").doesNotContain("私密草稿");
        get("/tickets/" + ticket, otherMerchant, 404);
        get("/tickets/" + ticket, buyer, 403);
        post(
                "/tickets/" + ticket + "/messages",
                merchant,
                "question",
                Map.of("expected_version", c.get("version").asLong(), "text", "请补充代收情况", "kind", "REQUEST_INFO"),
                200);
        c = get(path(c), buyer, 200);
        assertThat(c.get("ticket").get("status").asString()).isEqualTo("WAITING_CUSTOMER");
        c = message(c, "supplement", "没有授权代收", "MERCHANT");
        assertThat(c.get("ticket").get("status").asString()).isEqualTo("PENDING");
        detail = get("/tickets/" + ticket, merchant, 200);
        assertThat(detail.toString()).contains("没有授权代收").doesNotContain("私密草稿");
        assertThat(count("aftersale_case")).isEqualTo(cases);
        assertThat(count("case_authorization")).isEqualTo(auths);
        assertThat(count("active_case_slot")).isEqualTo(slots);
    }

    @Test
    void receiptWinsOverStaleVersionAndRejectsChangedPayload() {
        var c = open("support-A");
        var body = Map.of("expected_version", c.get("version").asLong(), "text", "原消息", "recipient", "ASSISTANT");
        var first = post(path(c) + "/messages", buyer, "same", body, 200);
        var newer = message(first, "next", "新消息", "ASSISTANT");
        assertThat(post(path(c) + "/messages", buyer, "same", body, 200)).isEqualTo(first);
        post(
                path(c) + "/messages",
                buyer,
                "same",
                Map.of("expected_version", 1, "text", "改过消息", "recipient", "ASSISTANT"),
                409);
        post(path(c) + "/messages", buyer, "stale", body, 409);
        assertThat(get(path(c), buyer, 200).get("version")).isEqualTo(newer.get("version"));
        assertThat(count("support_message")).isEqualTo(2);
    }

    @Test
    void noAutomaticSharingAndNoForeignOriginalCanBeTransferred() {
        var a = message(open("support-A"), "a", "A原文", "ASSISTANT");
        var b = message(open("support-B"), "b", "B原文", "ASSISTANT");
        post(
                path(a) + "/tickets",
                buyer,
                "foreign",
                Map.of(
                        "expected_version",
                        a.get("version").asLong(),
                        "summary",
                        "核查",
                        "shared_message_ids",
                        List.of(b.get("messages").get(0).get("message_id").asString())),
                400);
        a = post(
                path(a) + "/tickets",
                buyer,
                "empty",
                Map.of(
                        "expected_version",
                        a.get("version").asLong(),
                        "summary",
                        "只共享摘要",
                        "shared_message_ids",
                        List.of()),
                200);
        String ticket = a.get("ticket").get("ticket_id").asString();
        assertThat(get("/tickets/" + ticket, merchant, 200).toString()).doesNotContain("A原文");
        post(
                path(a) + "/tickets",
                buyer,
                "second",
                Map.of("expected_version", a.get("version").asLong(), "summary", "重复", "shared_message_ids", List.of()),
                409);
        assertThat(count("support_ticket")).isEqualTo(1);
    }

    @Test
    void onlyCustomerCanResolveAReplyAndSupplementReopensWithoutTwoRoundLimit() {
        var c = open("support-A");
        c = post(
                path(c) + "/tickets",
                buyer,
                "transfer",
                Map.of("expected_version", 1, "summary", "核查", "shared_message_ids", List.of()),
                200);
        post(
                path(c) + "/resolve",
                buyer,
                "early",
                Map.of("expected_version", c.get("version").asLong()),
                409);
        String ticket = c.get("ticket").get("ticket_id").asString();
        post(
                "/tickets/" + ticket + "/messages",
                merchant,
                "answer",
                Map.of("expected_version", c.get("version").asLong(), "text", "已记录情况，请确认问题是否解决", "kind", "REPLY"),
                200);
        c = get(path(c), buyer, 200);
        c = post(
                path(c) + "/resolve",
                buyer,
                "done",
                Map.of("expected_version", c.get("version").asLong()),
                200);
        assertThat(c.get("ticket").get("status").asString()).isEqualTo("RESOLVED");
        for (int n = 0; n < 4; n++) c = message(c, "more-" + n, "继续核查 " + n, "MERCHANT");
        assertThat(c.get("ticket").get("status").asString()).isEqualTo("PENDING");
        assertThat(get("/tickets/" + ticket, merchant, 200).get("messages").size())
                .isEqualTo(5);
    }

    @Test
    void unknownIdentityInputsAndInvalidParametersCannotWrite() {
        post("/conversations", buyer, null, Map.of("line_id", "support-A", "merchant_id", "M-1002"), 400);
        var c = open("support-A");
        post(
                path(c) + "/messages",
                buyer,
                null,
                Map.of("expected_version", 1, "text", "问题", "recipient", "ASSISTANT"),
                400);
        post(
                path(c) + "/messages",
                buyer,
                "invalid",
                Map.of("expected_version", 1, "text", " ", "recipient", "ASSISTANT"),
                400);
        post(
                path(c) + "/messages",
                buyer,
                "no-ticket",
                Map.of("expected_version", 1, "text", "发给商家", "recipient", "MERCHANT"),
                409);
        get("/conversations?limit=0", buyer, 400);
        get("/tickets?limit=51", merchant, 400);
        assertThat(count("support_message")).isZero();
    }

    @Test
    void concurrentSameKeyAppendsOnceAndConcurrentOldVersionsCannotBothWin() throws Exception {
        var c = open("support-A");
        String id = c.get("conversation_id").asString();
        var session = principals.session(buyer);
        var send = new com.resolveflow.shared.support.SupportWire.Send(1L, "并发同一消息", "ASSISTANT");
        try (var pool = java.util.concurrent.Executors.newFixedThreadPool(4)) {
            var futures = new java.util.ArrayList<
                    java.util.concurrent.Future<com.resolveflow.shared.support.SupportWire.Conversation>>();
            for (int i = 0; i < 4; i++) futures.add(pool.submit(() -> support.send(session, id, "concurrent", send)));
            for (var f : futures)
                assertThat(f.get(15, java.util.concurrent.TimeUnit.SECONDS).version())
                        .isEqualTo(2);
            assertThat(count("support_message")).isEqualTo(1);
            var start = new java.util.concurrent.CountDownLatch(1);
            var results = new java.util.ArrayList<java.util.concurrent.Future<Integer>>();
            for (int i = 0; i < 2; i++) {
                String key = "race-" + i;
                results.add(pool.submit(() -> {
                    start.await();
                    try {
                        support.send(
                                session,
                                id,
                                key,
                                new com.resolveflow.shared.support.SupportWire.Send(2L, key, "ASSISTANT"));
                        return 200;
                    } catch (SupportService.Refused e) {
                        return e.status;
                    }
                }));
            }
            start.countDown();
            assertThat(List.of(
                            results.get(0).get(15, java.util.concurrent.TimeUnit.SECONDS),
                            results.get(1).get(15, java.util.concurrent.TimeUnit.SECONDS)))
                    .containsExactlyInAnyOrder(200, 409);
        }
        assertThat(count("support_message")).isEqualTo(2);
    }

    @Test
    void historyAndListsHaveExplicitContinuationAndPrivateMessagesStayPrivate() {
        var c = open("support-A");
        String id = c.get("conversation_id").asString();
        var session = principals.session(buyer);
        for (long v = 1; v <= 53; v++)
            support.send(
                    session,
                    id,
                    "page-" + v,
                    new com.resolveflow.shared.support.SupportWire.Send(v, "第" + v + "条", "ASSISTANT"));
        c = get(path(c), buyer, 200);
        assertThat(c.get("messages").size()).isEqualTo(50);
        var older = get(
                path(c) + "?before_sequence=" + c.get("next_before_sequence").asLong(), buyer, 200);
        assertThat(older.get("messages").size()).isEqualTo(3);
        assertThat(older.get("next_before_sequence").isNull()).isTrue();
        String first = older.get("messages").get(0).get("message_id").asString();
        c = post(
                path(c) + "/tickets",
                buyer,
                "old-share",
                Map.of(
                        "expected_version",
                        c.get("version").asLong(),
                        "summary",
                        "核查",
                        "shared_message_ids",
                        List.of(first)),
                200);
        assertThat(get("/tickets/" + c.get("ticket").get("ticket_id").asString(), merchant, 200)
                        .get("ticket")
                        .get("shared_messages")
                        .get(0)
                        .get("message_id")
                        .asString())
                .isEqualTo(first);
        var b = open("support-B");
        var page = get("/conversations?limit=1", buyer, 200);
        assertThat(page.get("items").get(0).get("conversation_id")).isEqualTo(b.get("conversation_id"));
        var second =
                get("/conversations?limit=1&before=" + page.get("next_before").asLong(), buyer, 200);
        assertThat(second.get("items").get(0).get("conversation_id").asString()).isEqualTo(id);
        assertThat(second.get("next_before").isNull()).isTrue();
    }
}
