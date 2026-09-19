package com.resolveflow.caseservice.casefile;

import static org.assertj.core.api.Assertions.assertThat;

import com.resolveflow.caseservice.CaseDatabaseTest;
import com.resolveflow.shared.security.AuthenticatedPrincipal;
import com.resolveflow.shared.security.JwtCodec;
import com.resolveflow.shared.security.Role;
import java.time.Instant;
import java.util.List;
import java.util.Map;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.Future;
import java.util.concurrent.TimeUnit;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.resttestclient.autoconfigure.AutoConfigureRestTestClient;
import org.springframework.boot.test.context.TestConfiguration;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Primary;
import org.springframework.http.HttpHeaders;
import org.springframework.http.MediaType;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.test.web.servlet.client.RestTestClient;
import org.springframework.web.client.RestClient;
import tools.jackson.databind.JsonNode;
import tools.jackson.databind.ObjectMapper;

/**
 * {@code GET /api/v1/cases/{case_id}/events} (docs/core-contracts.md:32).
 *
 * <p>The stream is asserted by reading it to its end, which is only possible because a terminal case ends
 * its stream — so the completion rule is itself under test in every one of these. The live case test
 * subscribes first and then changes the case from another thread, because a stream that only replays would
 * pass any test that changed the case before subscribing.
 */
@AutoConfigureRestTestClient
class CaseEventStreamApiTest extends CaseDatabaseTest {

    private static final ObjectMapper MAPPER = new ObjectMapper();
    private static final String LINE = "7001";

    @Autowired
    RestTestClient rest;

    @Autowired
    StubCommerce commerce;

    @Autowired
    JwtCodec jwtCodec;

    @Autowired
    JdbcTemplate jdbc;

    @TestConfiguration
    static class StubCommerceConfiguration {

        @Bean
        @Primary
        StubCommerce stubCommerce(RestClient.Builder builder, JwtCodec jwtCodec) {
            return new StubCommerce(builder, jwtCodec);
        }
    }

    @BeforeEach
    void clean() {
        deleteAllCaseData(jdbc);
        commerce.lineVisible = true;
    }

    private static String token(JwtCodec codec, String user, String merchant, Role role, String customer) {
        return codec.issue(new AuthenticatedPrincipal(user, merchant, role, customer), Instant.now());
    }

    private String customer() {
        return token(jwtCodec, "demo-customer", "M-1001", Role.CUSTOMER, "C-2002");
    }

    private String openCase(String line) {
        String body = rest.post()
                .uri("/api/v1/cases")
                .header(HttpHeaders.AUTHORIZATION, "Bearer " + customer())
                .header("Idempotency-Key", "stream-key-" + System.nanoTime())
                .contentType(MediaType.APPLICATION_JSON)
                .body(Map.of("line_id", line, "description", "包裹疑似丢失", "requested_actions", List.of("REFUND")))
                .exchange()
                .expectStatus()
                .isCreated()
                .expectBody(String.class)
                .returnResult()
                .getResponseBody();
        return MAPPER.readTree(body).get("case_id").stringValue();
    }

    private void appendEvidence(String caseId) {
        rest.post()
                .uri("/api/v1/cases/" + caseId + "/evidence")
                .header(HttpHeaders.AUTHORIZATION, "Bearer " + customer())
                .contentType(MediaType.APPLICATION_JSON)
                .body(Map.of("text", "补充说明", "evidence_kind", "CUSTOMER_STATEMENT"))
                .exchange()
                .expectStatus()
                .isOk();
    }

    private void cancelCase(String caseId) {
        rest.post()
                .uri("/api/v1/cases/" + caseId + "/cancel")
                .header(HttpHeaders.AUTHORIZATION, "Bearer " + customer())
                .contentType(MediaType.APPLICATION_JSON)
                .body(Map.of("reason", "达成一致，不再需要退款"))
                .exchange()
                .expectStatus()
                .isOk();
    }

    /** Reads the stream to its end and returns the frames. Only terminates because a terminal case closes it. */
    private String readStream(String caseId, String token, String lastEventId) {
        RestTestClient.RequestHeadersSpec<?> request =
                rest.get().uri("/api/v1/cases/" + caseId + "/events").accept(MediaType.TEXT_EVENT_STREAM);
        if (token != null) {
            request = request.header(HttpHeaders.AUTHORIZATION, "Bearer " + token);
        }
        if (lastEventId != null) {
            request = request.header("Last-Event-ID", lastEventId);
        }
        return request.exchange()
                .expectStatus()
                .isOk()
                .expectBody(String.class)
                .returnResult()
                .getResponseBody();
    }

    private List<String> eventIds(String caseId) {
        return jdbc.queryForList(
                "SELECT event_id FROM case_timeline WHERE case_id = ? ORDER BY sequence", String.class, caseId);
    }

    @Test
    @DisplayName("the stream replays the trajectory in order and ends with the case")
    void theStreamReplaysAndEndsWithTheCase() {
        String caseId = openCase(LINE);
        appendEvidence(caseId);
        cancelCase(caseId);
        List<String> ids = eventIds(caseId);
        assertThat(ids).hasSize(3);

        String frames = readStream(caseId, customer(), null);

        assertThat(frames).as("the frames are one per stored event").contains("id:" + ids.get(0));
        int created = frames.indexOf("event:CASE_CREATED");
        int appended = frames.indexOf("event:EVIDENCE_APPENDED");
        int closed = frames.indexOf("event:CASE_CLOSED");
        assertThat(created).isGreaterThanOrEqualTo(0);
        assertThat(appended).as("the order is the order it happened").isGreaterThan(created);
        assertThat(closed).isGreaterThan(appended);

        // The data frame is the case view's event shape, not a second spelling of it.
        JsonNode data = MAPPER.readTree(frames.lines()
                .filter(line -> line.startsWith("data:"))
                .findFirst()
                .orElseThrow()
                .substring("data:".length())
                .trim());
        assertThat(data.properties().stream().map(Map.Entry::getKey))
                .containsExactlyInAnyOrder("event_id", "type", "occurred_at", "summary", "revision");
        assertThat(data.get("type").stringValue()).isEqualTo("CASE_CREATED");
    }

    @Test
    @DisplayName("Last-Event-ID resumes after the event the client already saw")
    void resumptionSkipsWhatTheClientSaw() {
        String caseId = openCase(LINE);
        appendEvidence(caseId);
        cancelCase(caseId);
        List<String> ids = eventIds(caseId);

        String frames = readStream(caseId, customer(), ids.get(0));

        assertThat(frames).as("the event the client reported is not sent again").doesNotContain(ids.get(0));
        assertThat(frames).contains(ids.get(1)).contains(ids.get(2));
        assertThat(frames).contains("event:EVIDENCE_APPENDED").contains("event:CASE_CLOSED");
    }

    @Test
    @DisplayName("an id this case never issued replays from the beginning and says so")
    void anUnknownEventIdReplaysFromTheBeginning() {
        String caseId = openCase(LINE);
        cancelCase(caseId);
        List<String> ids = eventIds(caseId);

        String frames = readStream(caseId, customer(), "00000000-0000-4000-8000-000000000000");

        assertThat(frames).as("a superset is more useful than a refusal").contains(ids.get(0));
        assertThat(frames)
                .as("and the client is told its resumption did not resume")
                .contains("unknown Last-Event-ID");
    }

    @Test
    @DisplayName("an event that happens while subscribed is delivered")
    void whatHappensWhileSubscribedIsDelivered() throws Exception {
        String caseId = openCase(LINE);
        ExecutorService pool = Executors.newSingleThreadExecutor();
        try {
            // Subscribe first, on a thread that blocks until the stream ends, then change the case.
            Future<String> frames = pool.submit(() -> readStream(caseId, customer(), null));
            Thread.sleep(1500);
            appendEvidence(caseId);
            Thread.sleep(1500);
            cancelCase(caseId);

            String body = frames.get(60, TimeUnit.SECONDS);
            assertThat(body).contains("event:CASE_CREATED");
            assertThat(body)
                    .as("the append arrived after the stream was already open")
                    .contains("event:EVIDENCE_APPENDED");
            assertThat(body).contains("event:CASE_CLOSED");
        } finally {
            pool.shutdownNow();
        }
    }

    @Test
    @DisplayName("a refusal before the stream starts is the ordinary error body")
    void refusalsHappenBeforeTheStreamStarts() {
        String caseId = openCase(LINE);
        String otherCustomer = token(jwtCodec, "demo-customer-2", "M-1001", Role.CUSTOMER, "C-2003");
        String otherMerchant = token(jwtCodec, "demo-reviewer-m2", "M-1002", Role.REVIEWER, null);

        rest.get()
                .uri("/api/v1/cases/" + caseId + "/events")
                .accept(MediaType.TEXT_EVENT_STREAM)
                .exchange()
                .expectStatus()
                .isUnauthorized()
                .expectBody(String.class)
                .value(body -> assertThat(MAPPER.readTree(body).get("code").stringValue())
                        .isEqualTo("UNAUTHENTICATED"));

        for (String token : List.of(otherCustomer, otherMerchant)) {
            rest.get()
                    .uri("/api/v1/cases/" + caseId + "/events")
                    .header(HttpHeaders.AUTHORIZATION, "Bearer " + token)
                    .accept(MediaType.TEXT_EVENT_STREAM)
                    .exchange()
                    .expectStatus()
                    .isNotFound();
        }

        rest.get()
                .uri("/api/v1/cases/00000000-0000-4000-8000-00000000dead/events")
                .header(HttpHeaders.AUTHORIZATION, "Bearer " + customer())
                .accept(MediaType.TEXT_EVENT_STREAM)
                .exchange()
                .expectStatus()
                .isNotFound();
    }
}
