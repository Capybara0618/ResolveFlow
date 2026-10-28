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
    SupportAgentTurns turns;

    @Autowired
    SupportAgentClient assistant;

    @Autowired
    com.resolveflow.shared.security.JwtCodec codec;

    @Autowired
    com.resolveflow.caseservice.order.RequestPrincipalResolver principals;

    final ObjectMapper json = new ObjectMapper();
    String buyer, merchant, otherMerchant, otherBuyer;

    @TestConfiguration
    static class Configuration {
        @Bean
        WakeProbe wakeProbe() {
            return new WakeProbe();
        }

        @Bean
        @Primary
        SupportAgentClient assistantStub() {
            return mock(SupportAgentClient.class);
        }

        @Bean
        @Primary
        CommerceOrderLineClient supportCommerce() {
            return mock(CommerceOrderLineClient.class);
        }
    }

    static class WakeProbe {
        final java.util.concurrent.atomic.AtomicInteger calls = new java.util.concurrent.atomic.AtomicInteger();

        @org.springframework.transaction.event.TransactionalEventListener
        public void committed(SupportAgentTurns.Queued event) {
            calls.incrementAndGet();
        }
    }

    @Autowired
    WakeProbe wakeProbe;

    @Test
    void wakeEventIsDeliveredAfterCommitAndNotAfterRollback() {
        int before = wakeProbe.calls.get();
        var c = message(open("support-A"), "wake-commit", "核查物流", "ASSISTANT");
        assertThat(wakeProbe.calls.get()).isEqualTo(before + 1);
        assertThatThrownBy(() -> new org.springframework.transaction.support.TransactionTemplate(transactionManager)
                        .executeWithoutResult(st -> {
                            turns.enqueue(
                                    principals.session(buyer),
                                    c.path("conversation_id").asString(),
                                    3);
                            throw new IllegalStateException("synthetic rollback");
                        }))
                .isInstanceOf(IllegalStateException.class);
        assertThat(wakeProbe.calls.get()).isEqualTo(before + 1);
        verifyNoInteractions(assistant);
    }

    @BeforeEach
    void prepare() {
        // Only this new module's rows in the disposable test container.
        for (String t : List.of(
                "support_receipt", "support_message", "support_ticket", "support_agent_turn", "support_conversation"))
            jdbc.update("DELETE FROM " + t);
        jdbc.update("INSERT IGNORE INTO platform_buyer(buyer_id) VALUES ('B-support-other')");
        jdbc.update(
                "INSERT IGNORE INTO identity_account(username,role,display_name,password_hash) SELECT 'support-platform','PLATFORM_ADMIN','Process admin',password_hash FROM identity_account WHERE username='demo-buyer'");
        jdbc.update("""
            INSERT IGNORE INTO identity_account(username,role,buyer_id,display_name,password_hash)
            SELECT 'support-other','CUSTOMER','B-support-other','Other',password_hash
            FROM identity_account WHERE username='demo-buyer'
            """);
        reset(commerce);
        reset(assistant);
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
    void privateStreamRefusesMissingOrOtherIdentitiesBeforeStarting() {
        var c = open("support-A");
        get(path(c) + "/events", null, 401);
        get(path(c) + "/events", otherBuyer, 404);
        get(path(c) + "/events", merchant, 404);
        get(path(c) + "/events", otherMerchant, 404);
        verifyNoInteractions(assistant);
    }

    @org.springframework.boot.test.web.server.LocalServerPort
    int httpPort;

    record StreamResult(java.net.http.HttpHeaders headers, List<JsonNode> events) {}

    StreamResult stream(JsonNode c, String cursor, int count, Runnable afterHeaders) throws Exception {
        var builder = java.net.http.HttpRequest.newBuilder(
                        java.net.URI.create("http://127.0.0.1:" + httpPort + "/api/v1/support" + path(c) + "/events"))
                .timeout(java.time.Duration.ofSeconds(6))
                .header("Authorization", buyer)
                .header("Accept", "text/event-stream");
        if (cursor != null) builder.header("Last-Event-ID", cursor);
        try (var client = java.net.http.HttpClient.newHttpClient()) {
            var response = client.send(builder.build(), java.net.http.HttpResponse.BodyHandlers.ofInputStream());
            assertThat(response.statusCode()).isEqualTo(200);
            try (var input = response.body();
                    var lines = new java.io.BufferedReader(
                            new java.io.InputStreamReader(input, java.nio.charset.StandardCharsets.UTF_8))) {
                afterHeaders.run();
                var events = new java.util.ArrayList<JsonNode>();
                while (events.size() < count) {
                    String line = lines.readLine();
                    assertThat(line).isNotNull();
                    if (line.startsWith("data:")) events.add(json.readTree(line.substring(5)));
                }
                return new StreamResult(response.headers(), events);
            }
        }
    }

    @Test
    void streamStartsWithSnapshotAndResumesOrderedEventsWithoutDispatching() throws Exception {
        var c = message(open("support-A"), "sse-first", "物流查询", "ASSISTANT");
        var initial = stream(c, null, 1, () -> {});
        assertThat(initial.headers.firstValue("Cache-Control")).contains("no-store");
        assertThat(initial.headers.firstValue("X-Accel-Buffering")).contains("no");
        var snapshot = initial.events.getFirst();
        assertThat(snapshot.path("kind").asString()).isEqualTo("stream.snapshot");
        assertThat(snapshot.path("event_id").asString()).isEqualTo("1");
        assertThat(snapshot.path("payload").path("conversation").path("version").asLong())
                .isEqualTo(2);
        c = message(c, "sse-second", "更正：还没收到", "ASSISTANT");
        var resumed = stream(c, "1", 2, () -> {}).events;
        assertThat(resumed.stream().map(e -> e.path("event_id").asString())).containsExactly("2", "3");
        assertThat(resumed.stream().map(e -> e.path("kind").asString()))
                .containsExactly("answer.stale", "turn.accepted");
        var reset = stream(c, "999999", 1, () -> {}).events.getFirst();
        assertThat(reset.path("kind").asString()).isEqualTo("stream.snapshot");
        assertThat(reset.path("event_id").asString()).isEqualTo("3");
        verifyNoInteractions(assistant);
    }

    @Test
    void alreadyConnectedStreamReceivesActualPublicationWithoutClientPolling() throws Exception {
        var c = message(open("support-A"), "sse-live", "请核查物流", "ASSISTANT");
        when(assistant.execute(anyString(), any())).thenAnswer(i -> {
            Map<String, Object> input = i.getArgument(1);
            return json.readTree(json.writeValueAsString(Map.of(
                    "run_id",
                    input.get("run_id"),
                    "conversation_id",
                    input.get("conversation_id"),
                    "input_version",
                    input.get("input_version"),
                    "status",
                    "SUCCEEDED",
                    "mode",
                    "mock",
                    "answer",
                    Map.of("text", "已核查，可继续补充。", "citations", List.of()))));
        });
        var events = stream(c, "0", 3, turns::dispatchOne).events;
        assertThat(events.stream().map(e -> e.path("kind").asString()))
                .containsExactly("turn.accepted", "turn.started", "answer.committed");
        assertThat(events.getLast().path("payload").path("text").asString()).isEqualTo("已核查，可继续补充。");
        verify(assistant, times(1)).execute(anyString(), any());
    }

    @Autowired
    SupportStreamEvents streamJournal;

    Map<String, Object> progressEvent(String kind, String attempt, Map<String, Object> payload) {
        var event = new java.util.LinkedHashMap<String, Object>();
        event.put("kind", kind);
        event.put("attempt_id", attempt);
        event.put("payload", payload);
        return event;
    }

    @Test
    void progressIsFencedSequencedProvisionalAndRestoredWithoutPublishing() throws Exception {
        var c = message(open("support-A"), "progress-ask", "请查物流", "ASSISTANT");
        String id = c.path("conversation_id").asString(),
                run = c.path("assistant_turn").path("run_id").asString();
        turns.claim();
        var bound = new com.resolveflow.shared.security.JwtCodec.SupportCredential(
                run, id, 2, 1, "M-1001", "C-B3001-M1001", "support-A");
        String progress = "Bearer " + codec.issueSupportProgressCredential(bound, Instant.now());
        String reader = "Bearer " + codec.issueSupportCredential(bound, Instant.now());
        String route = "/internal/v1/support/turns/" + run + "/stream-events";
        var batch = Map.of(
                "batch_sequence",
                1,
                "events",
                List.of(
                        progressEvent("answer.started", "a1", Map.of()),
                        progressEvent("answer.delta", "a1", Map.of("part_id", "part-0", "offset", 0, "text", "您好😀"))));
        postRaw(route, reader, null, batch, 403);
        postRaw(route, progress, null, batch, 200);
        postRaw(route, progress, null, batch, 200); // Same sequence/payload is idempotent.
        assertThat(get(path(c), buyer, 200).path("messages").size()).isEqualTo(1);
        assertThat(get(path(c), buyer, 200).path("version").asLong()).isEqualTo(2);
        var view =
                stream(c, null, 1, () -> {}).events.getFirst().path("payload").path("generation");
        assertThat(view.path("view").path("parts").path("part-0").asString()).isEqualTo("您好😀");
        postRaw(
                route,
                progress,
                null,
                Map.of(
                        "batch_sequence",
                        2,
                        "events",
                        List.of(progressEvent(
                                "answer.delta", "a1", Map.of("part_id", "part-0", "offset", 3, "text", "，核查中。")))),
                200);
        postRaw(
                route,
                progress,
                null,
                Map.of("batch_sequence", 3, "events", List.of(progressEvent("answer.committed", "a1", Map.of()))),
                409);
        postRaw(
                route,
                progress,
                null,
                Map.of("batch_sequence", 3, "events", List.of(progressEvent("answer.reset", "a2", Map.of()))),
                200);
        postRaw(
                route,
                progress,
                null,
                Map.of(
                        "batch_sequence",
                        4,
                        "events",
                        List.of(progressEvent(
                                "answer.delta", "a1", Map.of("part_id", "part-0", "offset", 0, "text", "旧草稿")))),
                409);
        c = message(c, "new-input", "更正一下", "ASSISTANT");
        postRaw(
                route,
                progress,
                null,
                Map.of(
                        "batch_sequence",
                        4,
                        "events",
                        List.of(progressEvent(
                                "answer.delta", "a2", Map.of("part_id", "part-0", "offset", 0, "text", "旧输入")))),
                409);
        verifyNoInteractions(assistant);
    }

    @Test
    void boundedOrExpiredHistoryRestoresSnapshotWithoutChangingInput() throws Exception {
        var c = message(open("support-A"), "sse-bounded", "查询", "ASSISTANT");
        String conversation = c.path("conversation_id").asString();
        String run = c.path("assistant_turn").path("run_id").asString();
        new org.springframework.transaction.support.TransactionTemplate(transactionManager).executeWithoutResult(st -> {
            for (int i = 0; i < 513; i++)
                streamJournal.append(conversation, run, 2, 0, "turn.accepted", Map.of("status", "PENDING"));
        });
        assertThat(jdbc.queryForObject(
                        "SELECT COUNT(*) FROM support_stream_event WHERE conversation_id=?", Long.class, conversation))
                .isEqualTo(512);
        var snapshot = stream(c, "1", 1, () -> {}).events.getFirst();
        assertThat(snapshot.path("kind").asString()).isEqualTo("stream.snapshot");
        assertThat(snapshot.path("event_id").asString()).isEqualTo("514");
        jdbc.update(
                "UPDATE support_stream_event SET created_at=TIMESTAMPADD(HOUR,-25,CURRENT_TIMESTAMP(6)) WHERE conversation_id=?",
                conversation);
        assertThat(stream(c, "513", 1, () -> {}).events.getFirst().path("kind").asString())
                .isEqualTo("stream.snapshot");
        assertThat(get(path(c), buyer, 200).path("version").asLong()).isEqualTo(2);
        verifyNoInteractions(assistant);
    }

    @Test
    void assistantPublishesOnceWithModeReferencesAndNoRefundSideEffects() {
        long cases = count("aftersale_case");
        var c = message(open("support-A"), "ask", "这个签收记录如何核查？", "ASSISTANT");
        when(assistant.execute(anyString(), any())).thenAnswer(i -> {
            Map<String, Object> input = i.getArgument(1);
            JsonNode context = (JsonNode) input.get("context");
            assertThat(context.get("conversation_state"))
                    .isEqualTo(json.readTree(json.writeValueAsString(Map.of(
                            "has_ticket",
                            false,
                            "ticket_status",
                            "NONE",
                            "current_recipient",
                            "ASSISTANT",
                            "default_recipient",
                            "ASSISTANT"))));
            return json.readTree(json.writeValueAsString(Map.of(
                    "run_id",
                    input.get("run_id"),
                    "conversation_id",
                    input.get("conversation_id"),
                    "input_version",
                    input.get("input_version"),
                    "status",
                    "SUCCEEDED",
                    "mode",
                    "mock",
                    "spend",
                    Map.of("model_calls", 2),
                    "answer",
                    Map.of("text", "可以请商家核查签收争议。", "citations", List.of(), "handoff_summary", "客户否认收到，请核查签收。"))));
        });
        assertThat(c.get("assistant_turn").get("status").asString()).isEqualTo("PENDING");
        long input = c.get("version").asLong();
        String conversation = c.get("conversation_id").asString();
        assertThat(jdbc.queryForList(
                        "SELECT kind FROM support_stream_event WHERE conversation_id=? ORDER BY event_id",
                        String.class,
                        conversation))
                .containsExactly("turn.accepted");
        turns.dispatchOne();
        turns.dispatchOne();
        c = get(path(c), buyer, 200);
        assertThat(c.get("messages").size()).isEqualTo(2);
        assertThat(c.get("messages").get(1).get("author").asString()).isEqualTo("ASSISTANT");
        assertThat(c.get("messages").get(1).get("assistant").get("mode").asString())
                .isEqualTo("mock");
        assertThat(c.get("assistant_turn").get("status").asString()).isEqualTo("SUCCEEDED");
        verify(assistant, times(1)).execute(anyString(), any());
        assertThat(count("aftersale_case")).isEqualTo(cases);
        assertThat(c.get("version").asLong()).isEqualTo(input + 1);
        assertThat(jdbc.queryForList(
                        "SELECT kind FROM support_stream_event WHERE conversation_id=? ORDER BY event_id",
                        String.class,
                        conversation))
                .containsExactly("turn.accepted", "turn.started", "answer.committed");
        var committed = json.readTree(jdbc.queryForObject(
                "SELECT payload_json FROM support_stream_event WHERE conversation_id=? AND kind='answer.committed'",
                String.class,
                conversation));
        assertThat(committed.path("message_id").asString())
                .isEqualTo(c.path("messages").get(1).path("message_id").asString());
        assertThat(committed.path("text").asString())
                .isEqualTo(c.path("messages").get(1).path("text").asString());
    }

    @Test
    void newInputInvalidatesOldTurnAndEventsHaveIndependentSequence() {
        var c = message(open("support-A"), "stream-first", "物流呢？", "ASSISTANT");
        c = message(c, "stream-second", "补充：家人也没收到。", "ASSISTANT");
        String conversation = c.path("conversation_id").asString();
        assertThat(c.path("version").asLong()).isEqualTo(3);
        assertThat(jdbc.queryForList(
                        "SELECT kind FROM support_stream_event WHERE conversation_id=? ORDER BY event_id",
                        String.class,
                        conversation))
                .containsExactly("turn.accepted", "answer.stale", "turn.accepted");
        assertThat(jdbc.queryForObject(
                        "SELECT event_sequence FROM support_conversation WHERE conversation_id=?",
                        Long.class,
                        conversation))
                .isEqualTo(3);
    }

    @Autowired
    org.springframework.transaction.PlatformTransactionManager transactionManager;

    @Test
    void turnAndAcceptedEventRollbackWithOriginalMessageTransaction() {
        var c = open("support-A");
        String conversation = c.path("conversation_id").asString();
        var session = principals.session(buyer);
        assertThatThrownBy(() -> new org.springframework.transaction.support.TransactionTemplate(transactionManager)
                        .executeWithoutResult(st -> {
                            turns.enqueue(session, conversation, 1);
                            throw new IllegalStateException("synthetic rollback");
                        }))
                .isInstanceOf(IllegalStateException.class);
        assertThat(jdbc.queryForObject(
                        "SELECT COUNT(*) FROM support_stream_event WHERE conversation_id=?", Long.class, conversation))
                .isZero();
        assertThat(jdbc.queryForObject(
                        "SELECT COUNT(*) FROM support_agent_turn WHERE conversation_id=?", Long.class, conversation))
                .isZero();
        assertThat(jdbc.queryForObject(
                        "SELECT event_sequence FROM support_conversation WHERE conversation_id=?",
                        Long.class,
                        conversation))
                .isZero();
    }

    @Test
    void anOldDispatcherCannotMarkTheNewFenceStale() {
        var c = message(open("support-A"), "fence-race", "核查物流", "ASSISTANT");
        when(assistant.execute(anyString(), any())).thenAnswer(i -> {
            Map<String, Object> input = i.getArgument(1);
            jdbc.update("UPDATE support_agent_turn SET fence=fence+1 WHERE run_id=?", input.get("run_id"));
            return json.readTree(json.writeValueAsString(Map.of(
                    "run_id",
                    input.get("run_id"),
                    "conversation_id",
                    input.get("conversation_id"),
                    "input_version",
                    input.get("input_version"),
                    "status",
                    "FAILED",
                    "reason",
                    "OLD_RESULT")));
        });
        turns.dispatchOne();
        var live = get(path(c), buyer, 200);
        assertThat(live.get("assistant_turn").get("status").asString()).isEqualTo("RUNNING");
        assertThat(live.get("messages").size()).isEqualTo(1);
    }

    @Test
    void assistantAfterHandoffReceivesTrustedTicketStateSeparateFromCurrentPrivateRecipient() {
        var c = open("support-A");
        c = post(
                path(c) + "/tickets",
                buyer,
                "state-handoff",
                Map.of(
                        "expected_version",
                        c.get("version").asLong(),
                        "summary",
                        "仅核查",
                        "shared_message_ids",
                        List.of()),
                200);
        message(c, "private-state", "我想私下问一下", "ASSISTANT");
        when(assistant.execute(anyString(), any())).thenAnswer(i -> {
            Map<String, Object> input = i.getArgument(1);
            JsonNode context = (JsonNode) input.get("context");
            assertThat(context.get("conversation_state"))
                    .isEqualTo(json.readTree(json.writeValueAsString(Map.of(
                            "has_ticket",
                            true,
                            "ticket_status",
                            "PENDING",
                            "current_recipient",
                            "ASSISTANT",
                            "default_recipient",
                            "MERCHANT"))));
            return json.readTree(json.writeValueAsString(Map.of(
                    "run_id",
                    input.get("run_id"),
                    "conversation_id",
                    input.get("conversation_id"),
                    "input_version",
                    input.get("input_version"),
                    "status",
                    "FAILED",
                    "reason",
                    "TEST_ONLY")));
        });
        turns.dispatchOne();
        verify(assistant, times(1)).execute(anyString(), any());
        assertThat(get(path(c), buyer, 200).get("assistant_turn").get("reason").asString())
                .isEqualTo("TEST_ONLY");
        var state = jdbc.queryForObject(
                "SELECT context_json FROM support_agent_turn WHERE conversation_id=?",
                String.class,
                c.get("conversation_id").asString());
        assertThat(json.readTree(state).get("conversation_state"))
                .isEqualTo(json.readTree(json.writeValueAsString(Map.of(
                        "has_ticket",
                        true,
                        "ticket_status",
                        "PENDING",
                        "current_recipient",
                        "ASSISTANT",
                        "default_recipient",
                        "MERCHANT"))));
    }

    @Test
    void agentReportIsSharedOnlyAfterConfirmationAndNeverIncludesPrivateHistoryCitation() {
        var c = message(open("support-A"), "ask-report", "请核查签收，不申请退款。", "ASSISTANT");
        when(assistant.execute(anyString(), any())).thenAnswer(i -> {
            Map<String, Object> input = i.getArgument(1);
            var shipment = Map.of(
                    "source_id",
                    "O1",
                    "source_type",
                    "SHIPMENT",
                    "version",
                    3,
                    "content_hash",
                    "a".repeat(64),
                    "data",
                    Map.of("status", "DELIVERED"));
            var privateHistory = Map.of(
                    "source_id",
                    "O2",
                    "source_type",
                    "CONVERSATION",
                    "version",
                    2,
                    "content_hash",
                    "b".repeat(64),
                    "data",
                    Map.of("text", "私人历史不交给商家"));
            var guide = Map.of(
                    "source_id",
                    "O3",
                    "source_type",
                    "KNOWLEDGE",
                    "version",
                    "2026.10.21-v1",
                    "content_hash",
                    "c".repeat(64),
                    "data",
                    Map.of("authority", "APPLICATION_GUIDE", "text", "人工核查不需要先申请退款。"));
            return json.readTree(json.writeValueAsString(Map.of(
                    "run_id",
                    input.get("run_id"),
                    "conversation_id",
                    input.get("conversation_id"),
                    "input_version",
                    input.get("input_version"),
                    "status",
                    "SUCCEEDED",
                    "mode",
                    "mock",
                    "answer",
                    Map.of(
                            "text",
                            "建议核查签收。",
                            "citations",
                            List.of(shipment, privateHistory, guide),
                            "handoff_summary",
                            "客户否认收到，请核验签收。"))));
        });
        turns.dispatchOne();
        c = get(path(c), buyer, 200);
        String messageId = c.get("messages").get(1).get("message_id").asString();
        assertThat(get("/tickets", merchant, 200).get("items").size()).isZero();
        c = post(
                path(c) + "/tickets",
                buyer,
                "confirm-report",
                Map.of(
                        "expected_version",
                        c.get("version").asLong(),
                        "summary",
                        "客户确认：只核查",
                        "shared_message_ids",
                        List.of(),
                        "assistant_message_id",
                        messageId),
                200);
        var report = get("/tickets/" + c.get("ticket").get("ticket_id").asString(), merchant, 200);
        assertThat(report.get("ticket").get("report").get("citations").size()).isEqualTo(2);
        assertThat(report.toString()).contains("DELIVERED").doesNotContain("私人历史不交给商家");
        assertThat(report.toString()).contains("APPLICATION_GUIDE").contains("人工核查不需要先申请退款");
    }

    private JsonNode failedPauseUpdate(Map<String, Object> input) {
        var result = json.createObjectNode().put("status", "FAILED").put("mode", "mock");
        result.put("reason", "INVALID_DECISION");
        result.putNull("answer");
        var update = result.putObject("conversation_update").put("version", "support-state-v1");
        for (String key : List.of("run_id", "conversation_id", "merchant_id", "customer_id", "line_id")) {
            update.put(key, input.get(key).toString());
            if (List.of("run_id", "conversation_id").contains(key))
                result.put(key, input.get(key).toString());
        }
        long version = ((Number) input.get("input_version")).longValue();
        update.put("input_version", version);
        result.put("input_version", version);
        var state = update.putObject("task_state").put("origin", "MODEL");
        state.putArray("focus_ids");
        var task = state.putArray("tasks").addObject();
        task.put("id", "trace").put("intent", "LOGISTICS").put("request", "查签收");
        task.put("status", "SUSPENDED").put("lifecycle", "PAUSED");
        task.putArray("evidence_refs");
        task.putNull("response_excerpt");
        var memory = update.putObject("customer_memory").put("version", "support-claims-v1");
        memory.put("origin", "GROUNDED_CUSTOMER_CLAIMS").put("input_version", version);
        for (String key : List.of("conversation_id", "merchant_id", "customer_id", "line_id"))
            memory.put(key, input.get(key).toString());
        memory.putArray("entries");
        update.putArray("memory_warnings");
        var event = update.putObject("dialogue_state").putArray("events").addObject();
        event.put("change", "PAUSE").put("task_id", "trace");
        event.putObject("source")
                .put("sequence", version)
                .put("offset", 0)
                .put(
                        "quote",
                        ((JsonNode) input.get("context"))
                                .path("current_request")
                                .asString());
        return result;
    }

    @Test
    void acceptedPauseSurvivesFailedReplyWithoutPublishingDraftAndCanBeInherited() {
        var contexts = new java.util.ArrayList<JsonNode>();
        when(assistant.execute(anyString(), any())).thenAnswer(i -> {
            Map<String, Object> input = i.getArgument(1);
            contexts.add((JsonNode) input.get("context"));
            if (contexts.size() == 1) return failedPauseUpdate(input);
            return json.readTree(json.writeValueAsString(Map.of(
                    "run_id",
                    input.get("run_id"),
                    "conversation_id",
                    input.get("conversation_id"),
                    "input_version",
                    input.get("input_version"),
                    "status",
                    "SUCCEEDED",
                    "mode",
                    "mock",
                    "answer",
                    Map.of("text", "继续处理", "citations", List.of()))));
        });
        var c = message(open("support-A"), "pause-fail", "先暂停签收调查。", "ASSISTANT");
        long pausedInput = c.path("version").asLong();
        turns.dispatchOne();
        c = get(path(c), buyer, 200);
        assertThat(c.path("assistant_turn").path("status").asString()).isEqualTo("FAILED");
        assertThat(c.path("messages").size()).isEqualTo(1);
        assertThat(c.toString()).doesNotContain("conversation_update").doesNotContain("task_state");
        c = message(c, "resume-after-fail", "继续刚才的签收调查。", "ASSISTANT");
        turns.dispatchOne();
        var prior = contexts.get(1).path("previous_tasks");
        assertThat(prior.path("input_version").asLong()).isEqualTo(pausedInput);
        assertThat(prior.path("tasks").get(0).path("lifecycle").asString()).isEqualTo("PAUSED");
        assertThat(get(path(c), buyer, 200)
                        .path("assistant_turn")
                        .path("status")
                        .asString())
                .isEqualTo("SUCCEEDED");
    }

    @org.junit.jupiter.params.ParameterizedTest
    @org.junit.jupiter.params.provider.ValueSource(strings = {"line_id", "quote", "input_version"})
    void foreignStateOrFabricatedCurrentQuoteCannotBeInheritedFromFailedReply(String corruption) {
        var contexts = new java.util.ArrayList<JsonNode>();
        when(assistant.execute(anyString(), any())).thenAnswer(i -> {
            Map<String, Object> input = i.getArgument(1);
            contexts.add((JsonNode) input.get("context"));
            var result = failedPauseUpdate(input);
            var update = (tools.jackson.databind.node.ObjectNode) result.path("conversation_update");
            if (corruption.equals("line_id")) update.put("line_id", "foreign-product");
            if (corruption.equals("input_version")) update.put("input_version", 9999);
            if (corruption.equals("quote"))
                ((tools.jackson.databind.node.ObjectNode) update.path("dialogue_state")
                                .path("events")
                                .get(0)
                                .path("source"))
                        .put("quote", "不存在的原文");
            return result;
        });
        var c = message(open("support-A"), "foreign-state", "先暂停。", "ASSISTANT");
        turns.dispatchOne();
        c = get(path(c), buyer, 200);
        assertThat(c.path("assistant_turn").path("reason").asString()).isEqualTo("AGENT_PROTOCOL_INVALID");
        c = message(c, "after-foreign-state", "继续。", "ASSISTANT");
        turns.dispatchOne();
        assertThat(contexts.get(1).path("previous_tasks").isMissingNode()).isTrue();
    }

    @Test
    void previousModelTasksAreFrozenForSameConversationOnlyAndNotPublishedAsCustomerMetadata() {
        var contexts = new java.util.ArrayList<JsonNode>();
        var state = Map.of(
                "origin",
                "MODEL",
                "tasks",
                List.of(Map.of(
                        "id",
                        "refund",
                        "intent",
                        "ELIGIBILITY",
                        "request",
                        "私人退款诉求",
                        "status",
                        "NEEDS_CUSTOMER",
                        "evidence_refs",
                        List.of(),
                        "response_excerpt",
                        "请补充情况")));
        when(assistant.execute(anyString(), any())).thenAnswer(i -> {
            Map<String, Object> input = i.getArgument(1);
            contexts.add((JsonNode) input.get("context"));
            return json.readTree(json.writeValueAsString(Map.of(
                    "run_id",
                    input.get("run_id"),
                    "conversation_id",
                    input.get("conversation_id"),
                    "input_version",
                    input.get("input_version"),
                    "status",
                    "SUCCEEDED",
                    "mode",
                    "mock",
                    "answer",
                    Map.of("text", "请补充情况", "citations", List.of(), "task_state", state))));
        });
        var c = message(open("support-A"), "task-first", "了解退款", "ASSISTANT");
        long firstInput = c.get("version").asLong();
        turns.dispatchOne();
        c = get(path(c), buyer, 200);
        assertThat(c.toString()).doesNotContain("task_state").doesNotContain("私人退款诉求");
        c = message(c, "task-correct", "不退款了，只查物流", "ASSISTANT");
        turns.dispatchOne();
        var other = message(open("support-B"), "task-other", "查询本商品物流", "ASSISTANT");
        turns.dispatchOne();
        assertThat(contexts.size()).isEqualTo(3);
        assertThat(contexts.get(0).path("previous_tasks").isMissingNode()
                        || contexts.get(0).path("previous_tasks").isNull())
                .isTrue();
        assertThat(contexts.get(1).path("previous_tasks").path("origin").asString())
                .isEqualTo("MODEL_PREVIOUS_TURN");
        assertThat(contexts.get(1).path("previous_tasks").path("input_version").asLong())
                .isEqualTo(firstInput);
        assertThat(contexts.get(1)
                        .path("previous_tasks")
                        .path("tasks")
                        .get(0)
                        .path("request")
                        .asString())
                .isEqualTo("私人退款诉求");
        assertThat(contexts.get(2).path("previous_tasks").isMissingNode()
                        || contexts.get(2).path("previous_tasks").isNull())
                .isTrue();
        assertThat(get(path(c), buyer, 200).get("assistant_turn").get("status").asString())
                .isEqualTo("SUCCEEDED");
        assertThat(get(path(other), buyer, 200)
                        .get("assistant_turn")
                        .get("status")
                        .asString())
                .isEqualTo("SUCCEEDED");
    }

    @Test
    void customerMemorySurvivesTurnsWithUnicodeQuoteAndStaysPrivateAndBoundToProduct() {
        var contexts = new java.util.ArrayList<JsonNode>();
        var memory = json.createObjectNode();
        when(assistant.execute(anyString(), any())).thenAnswer(i -> {
            Map<String, Object> input = i.getArgument(1);
            var context = (JsonNode) input.get("context");
            contexts.add(context);
            if (contexts.size() == 1) {
                memory.put("version", "support-claims-v1");
                memory.put("origin", "GROUNDED_CUSTOMER_CLAIMS");
                for (String key : List.of("conversation_id", "merchant_id", "customer_id", "line_id"))
                    memory.put(key, input.get(key).toString());
                memory.put("input_version", ((Number) input.get("input_version")).longValue());
                var entry = memory.putArray("entries").addObject();
                entry.put("id", "receipt");
                entry.put("topic", "RECEIPT");
                entry.put("status", "ACTIVE");
                entry.put("quote", "家人未代收");
                entry.putArray("supersedes");
                entry.putArray("retracts");
                var source = entry.putObject("source");
                source.putNull("message_id");
                source.put("sequence", ((Number) input.get("input_version")).longValue());
                source.put("offset", 1);
                source.put("quote", "家人未代收");
            }
            var answer = json.createObjectNode().put("text", "请商家核查。");
            answer.putArray("citations");
            if (contexts.size() <= 2) {
                var own = memory.deepCopy();
                own.put("input_version", ((Number) input.get("input_version")).longValue());
                answer.set("customer_memory", own);
            }
            var result = json.createObjectNode().put("status", "SUCCEEDED").put("mode", "mock");
            result.put("run_id", input.get("run_id").toString());
            result.put("conversation_id", input.get("conversation_id").toString());
            result.put("input_version", ((Number) input.get("input_version")).longValue());
            result.set("answer", answer);
            return result;
        });
        var c = message(open("support-A"), "memory-first", "😀家人未代收", "ASSISTANT");
        turns.dispatchOne();
        c = get(path(c), buyer, 200);
        assertThat(c.get("assistant_turn").get("status").asString()).isEqualTo("SUCCEEDED");
        assertThat(c.toString()).doesNotContain("customer_memory").doesNotContain("GROUNDED_CUSTOMER_CLAIMS");
        c = message(c, "memory-next", "继续核查", "ASSISTANT");
        turns.dispatchOne();
        var other = message(open("support-B"), "memory-other", "查另一商品", "ASSISTANT");
        turns.dispatchOne();
        assertThat(contexts.size()).isEqualTo(3);
        assertThat(contexts.get(1)
                        .path("previous_customer_memory")
                        .path("entries")
                        .get(0)
                        .path("quote")
                        .asString())
                .isEqualTo("家人未代收");
        assertThat(contexts.get(2).path("previous_customer_memory").isMissingNode())
                .isTrue();
        assertThat(get(path(c), buyer, 200).get("assistant_turn").get("status").asString())
                .isEqualTo("SUCCEEDED");
        assertThat(get(path(other), buyer, 200)
                        .get("assistant_turn")
                        .get("status")
                        .asString())
                .isEqualTo("SUCCEEDED");
    }

    @Test
    void correctionArrivingDuringGenerationPreventsOldReplyPublication() {
        var c = message(open("support-A"), "ask", "没有收到，先帮我核查。", "ASSISTANT");
        final String id = c.get("conversation_id").asString();
        when(assistant.execute(anyString(), any())).thenAnswer(i -> {
            var live = get("/conversations/" + id, buyer, 200);
            message(live, "correction", "找到了，不用核查。", "ASSISTANT");
            Map<String, Object> input = i.getArgument(1);
            return json.readTree(json.writeValueAsString(Map.of(
                    "run_id",
                    input.get("run_id"),
                    "conversation_id",
                    id,
                    "input_version",
                    input.get("input_version"),
                    "status",
                    "SUCCEEDED",
                    "mode",
                    "mock",
                    "answer",
                    Map.of("text", "过时回复不该出现", "citations", List.of()))));
        });
        turns.dispatchOne();
        c = get(path(c), buyer, 200);
        assertThat(c.toString()).doesNotContain("过时回复不该出现");
        assertThat(c.get("messages").size()).isEqualTo(2);
        assertThat(jdbc.queryForObject("SELECT COUNT(*) FROM support_agent_turn WHERE status='STALE'", Long.class))
                .isEqualTo(1);
    }

    @Test
    void consultationCredentialCannotReadOtherRunAndOldFenceCannotReadCurrentFacts() {
        var c = message(open("support-A"), "ask", "查物流", "ASSISTANT");
        when(assistant.execute(anyString(), any())).thenAnswer(i -> {
            Map<String, Object> body = i.getArgument(1);
            String token = "Bearer " + body.get("tool_token");
            String prefix = "/internal/v1/support/turns/" + body.get("run_id");
            rest.get()
                    .uri(prefix + "/current")
                    .header("Authorization", token)
                    .exchange()
                    .expectStatus()
                    .isOk();
            rest.get()
                    .uri("/internal/v1/support/turns/foreign/current")
                    .header("Authorization", token)
                    .exchange()
                    .expectStatus()
                    .isForbidden();
            rest.get()
                    .uri(prefix + "/facts/order")
                    .header("Authorization", token)
                    .exchange()
                    .expectStatus()
                    .isOk();
            rest.get()
                    .uri(prefix + "/facts/order")
                    .header("Authorization", buyer)
                    .exchange()
                    .expectStatus()
                    .isForbidden();
            jdbc.update("UPDATE support_agent_turn SET fence=fence+1 WHERE run_id=?", body.get("run_id"));
            rest.get()
                    .uri(prefix + "/current")
                    .header("Authorization", token)
                    .exchange()
                    .expectStatus()
                    .isEqualTo(409);
            return json.readTree("{\"status\":\"FAILED\",\"reason\":\"STALE_INPUT\"}");
        });
        turns.dispatchOne();
        assertThat(get(path(c), buyer, 200).get("messages").size()).isEqualTo(1);
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
    void platformProcessViewIsReadOnlyAndNeverIncludesPrivateTextOrEventPayloads() {
        var c = message(open("support-A"), "process-private", "PRIVATE-BUYER-TEXT", "ASSISTANT");
        String run = c.path("assistant_turn").path("run_id").asString();
        jdbc.update(
                "UPDATE support_agent_turn SET status='FAILED',reason=?,result_json=? WHERE run_id=?",
                "PRIVATE-FAILURE-DETAIL",
                "{\"mode\":\"mock\",\"spend\":{\"model_calls\":3},"
                        + "\"answer\":{\"text\":\"PRIVATE-ANSWER\",\"citations\":[{\"source_type\":\"POLICY\","
                        + "\"data\":{\"text\":\"PRIVATE-POLICY-QUERY\"}}]}}",
                run);
        String conversation = c.path("conversation_id").asString();
        jdbc.update(
                "INSERT INTO support_stream_event(conversation_id,event_id,run_id,input_version,fence,kind,payload_json) VALUES(?,100,?,2,0,'activity.started',?)",
                conversation,
                run,
                "{\"category\":\"SHIPMENT\",\"text\":\"PRIVATE-TOOL-REQUEST\"}");
        jdbc.update(
                "INSERT INTO support_stream_event(conversation_id,event_id,run_id,input_version,fence,kind,payload_json) VALUES(?,101,?,2,0,'answer.delta',?)",
                conversation,
                run,
                "{\"text\":\"PRIVATE-STREAM\"}");
        String platform = login("support-platform", "demo-pass-4001");
        var before = jdbc.queryForList("SELECT run_id,status,fence FROM support_agent_turn");
        var list = platformGet("", platform, 200);
        assertThat(list.path("items").size()).isEqualTo(1);
        var view = platformGet("/" + run, platform, 200);
        assertThat(view.path("run").path("model_requests").asInt()).isEqualTo(3);
        assertThat(view.path("events").toString()).contains("SHIPMENT").doesNotContain("answer.delta");
        assertThat(view.path("run").path("source_counts").path("POLICY").asInt())
                .isEqualTo(1);
        assertThat(list.toString() + view).doesNotContain("PRIVATE-", "context_json", "customer_id", "conversation_id");
        assertThat(view.path("run").path("reason").asString()).isEqualTo("UNAVAILABLE");
        assertThat(jdbc.queryForList("SELECT run_id,status,fence FROM support_agent_turn"))
                .isEqualTo(before);
        verifyNoInteractions(assistant);
    }

    @Test
    void processViewRejectsBuyerMerchantAndInvalidatedPlatformIdentity() {
        var c = message(open("support-A"), "process-scope", "private", "ASSISTANT");
        String path = "/" + c.path("assistant_turn").path("run_id").asString();
        for (String token : List.of(buyer, merchant, otherMerchant)) {
            platformGet("", token, 403);
            platformGet(path, token, 403);
        }
        platformGet("", null, 401);
        String platform = login("support-platform", "demo-pass-4001");
        platformGet("/00000000-0000-4000-8000-000000000000", platform, 404);
        jdbc.update(
                "UPDATE identity_account SET identity_version=identity_version+1 WHERE username='support-platform'");
        platformGet(path, platform, 401);
    }

    JsonNode platformGet(String suffix, String auth, int status) {
        var req = rest.get().uri("/api/v1/platform/support-runs" + suffix);
        if (auth != null) req.header("Authorization", auth);
        return json.readTree(req.exchange()
                .expectStatus()
                .isEqualTo(status)
                .expectBody(String.class)
                .returnResult()
                .getResponseBody());
    }

    @Test
    void processHistoryIsBoundedChronologicalAndMissingMetricsStayUnknown() {
        var c = message(open("support-A"), "process-bound", "private", "ASSISTANT");
        String run = c.path("assistant_turn").path("run_id").asString();
        for (int i = 0; i < 201; i++) {
            jdbc.update(
                    "INSERT INTO support_stream_event(conversation_id,event_id,run_id,input_version,fence,kind,payload_json,created_at) VALUES(?,?,?,2,0,'activity.completed',?,?)",
                    c.path("conversation_id").asString(),
                    100 + i,
                    run,
                    i % 2 == 0 ? "{\"category\":\"ORDER\"}" : "{\"category\":\"POLICY\"}",
                    java.sql.Timestamp.from(
                            Instant.parse("2026-10-01T00:00:00Z").plusSeconds(i)));
        }
        var view = platformGet("/" + run, login("support-platform", "demo-pass-4001"), 200);
        assertThat(view.path("events_truncated").asBoolean()).isTrue();
        assertThat(view.path("events").size()).isEqualTo(200);
        assertThat(view.path("events").get(0).path("category").asString()).isEqualTo("POLICY");
        assertThat(view.path("events").get(199).path("category").asString()).isEqualTo("ORDER");
        assertThat(view.path("run").path("model_requests").isNull()).isTrue();
        assertThat(view.path("run").path("mode").isNull()).isTrue();
        verifyNoInteractions(assistant);
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
