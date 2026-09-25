package com.resolveflow.caseservice.casefile;

import static org.assertj.core.api.Assertions.assertThat;

import com.resolveflow.caseservice.CaseDatabaseTest;
import com.resolveflow.shared.security.AuthenticatedPrincipal;
import com.resolveflow.shared.security.JwtCodec;
import com.resolveflow.shared.security.Role;
import java.time.Instant;
import java.util.List;
import java.util.Map;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.resttestclient.autoconfigure.AutoConfigureRestTestClient;
import org.springframework.boot.test.context.TestConfiguration;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Primary;
import org.springframework.http.HttpHeaders;
import org.springframework.http.HttpStatus;
import org.springframework.http.MediaType;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.test.web.servlet.client.RestTestClient;
import org.springframework.web.client.RestClient;
import tools.jackson.databind.JsonNode;
import tools.jackson.databind.ObjectMapper;

/**
 * C06.4⑤: {@code GET /internal/v1/cases/{case_id}/evidence} — the evidence half of the Agent's read surface.
 *
 * <p>The route is declared by the contract (C00) and, until this slice, <b>had no implementation at all</b>.
 * That is the same class of gap C06.2c found for {@code refund-status}, and it stayed invisible for the same
 * reason: the Python tool that depends on it is only ever tested against a stub, and <b>a stub answers whatever
 * it is told to</b> — so a tool reading a route nobody serves looks exactly like a working tool. It was found by
 * asking which routes the five tools actually need and grepping the Java for them, which is the check the
 * end-to-end step exists to force.
 *
 * <p>What is asserted is the contract's {@code EvidenceListResponse} member for member, plus the two facts that
 * make the route usable rather than merely present:
 *
 * <ul>
 *   <li><b>It is the case's current revision, not the run's.</b> A run decides about a revision
 *       ({@code docs/agent-spec.md:9}); this route reports what the case holds <em>now</em>, and the caller (the
 *       Agent's tool) records the version it actually read so a citation can be checked for staleness later.
 *   <li><b>{@code source_version} is the revision the material was appended at</b>, stored per record — not
 *       re-derived from the case. Re-deriving it would make every historical record claim to be current, which
 *       is exactly the staleness a citation check exists to catch.
 * </ul>
 *
 * <p>The shape matters as much as the behaviour here: {@code EvidenceRef.source_version} is a required,
 * non-empty <em>string</em>, and a record read back with a null version would make the Agent's observation
 * unparseable (the same failure mode C06.4② hit on the tool side).
 */
@AutoConfigureRestTestClient
class CaseEvidenceInternalApiTest extends CaseDatabaseTest {

    private static final ObjectMapper MAPPER = new ObjectMapper();
    private static final String LINE = "7001";

    @TestConfiguration
    static class StubCommerceConfiguration {

        @Bean
        @Primary
        StubCommerce stubCommerce(RestClient.Builder builder, JwtCodec jwtCodec) {
            return new StubCommerce(builder, jwtCodec);
        }
    }

    @Autowired
    RestTestClient rest;

    @Autowired
    JwtCodec jwtCodec;

    @Autowired
    JdbcTemplate jdbc;

    @BeforeEach
    void clean() {
        deleteAllCaseData(jdbc);
    }

    private String customer() {
        return jwtCodec.issue(
                new AuthenticatedPrincipal("demo-customer", "M-1001", Role.CUSTOMER, "C-2002"), Instant.now());
    }

    /** The service token the Agent presents on the internal surface. */
    private String service() {
        return jwtCodec.issueServiceToken("agent-service", Instant.now());
    }

    private String openCase() {
        String body = rest.post()
                .uri("/api/v1/cases")
                .header(HttpHeaders.AUTHORIZATION, "Bearer " + customer())
                .header("Idempotency-Key", "internal-evidence-" + System.nanoTime())
                .contentType(MediaType.APPLICATION_JSON)
                .body(Map.of("line_id", LINE, "description", "包裹疑似丢失", "requested_actions", List.of("REFUND")))
                .exchange()
                .expectStatus()
                .isCreated()
                .expectBody(String.class)
                .returnResult()
                .getResponseBody();
        return MAPPER.readTree(body).get("case_id").stringValue();
    }

    /** Appends one customer statement through the public route, which is how material really arrives. */
    private void appendEvidence(String caseId, String text) {
        rest.post()
                .uri("/api/v1/cases/" + caseId + "/evidence")
                .header(HttpHeaders.AUTHORIZATION, "Bearer " + customer())
                .contentType(MediaType.APPLICATION_JSON)
                .body(Map.of("text", text, "evidence_kind", "CUSTOMER_STATEMENT"))
                .exchange()
                .expectStatus()
                .isOk();
    }

    private JsonNode readInternalEvidence(String caseId) {
        String body = rest.get()
                .uri("/internal/v1/cases/" + caseId + "/evidence")
                .header(HttpHeaders.AUTHORIZATION, "Bearer " + service())
                .exchange()
                .expectStatus()
                .isOk()
                .expectBody(String.class)
                .returnResult()
                .getResponseBody();
        return MAPPER.readTree(body);
    }

    // ── the shape ─────────────────────────────────────────────────────────────────────────────────

    @Test
    @DisplayName("the internal read answers the contract's EvidenceListResponse, member for member")
    void theRouteAnswersTheContractsShape() {
        String caseId = openCase();
        appendEvidence(caseId, "包裹显示已揽收但 7 天无新物流");

        JsonNode answer = readInternalEvidence(caseId);

        // additionalProperties: false — the member set is asserted, not just the members we happen to read.
        assertThat(answer.propertyNames()).containsExactlyInAnyOrder("case_id", "input_revision", "evidence");
        assertThat(answer.get("case_id").stringValue()).isEqualTo(caseId);
        // The case is at revision 2 after one append: the append moved it, and the answer reports where it is.
        assertThat(answer.get("input_revision").asInt()).isEqualTo(2);

        assertThat(answer.get("evidence").size()).isEqualTo(1);
        JsonNode ref = answer.get("evidence").get(0);
        assertThat(ref.propertyNames())
                .containsExactlyInAnyOrder("observation_id", "source_ref", "source_version", "content_hash");
        assertThat(ref.get("observation_id").stringValue()).isNotBlank();
        assertThat(ref.get("source_version").stringValue()).isEqualTo("2");
        // content_hash is the sha-256 the record was stored with, so a citation can be re-checked against it.
        assertThat(ref.get("content_hash").stringValue()).hasSize(64);
        // A reference is a controlled value, never a requestable address (docs/core-contracts.md:61).
        assertThat(ref.get("source_ref").stringValue()).isNotBlank().doesNotStartWith("http");
    }

    @Test
    @DisplayName("a case with no material answers an empty list, not a 404")
    void anEmptyCaseAnswersAnEmptyList() {
        String caseId = openCase();

        JsonNode answer = readInternalEvidence(caseId);

        // "This case holds nothing" is an answer; a 404 would say the case does not exist, and the Agent would
        // record NOT_FOUND — which docs/agent-spec.md:36 says is not a negative fact. An empty list is the
        // honest form for "I read it and there is nothing there".
        assertThat(answer.get("input_revision").asInt()).isEqualTo(1);
        assertThat(answer.get("evidence").isArray()).isTrue();
        assertThat(answer.get("evidence").size()).isZero();
    }

    @Test
    @DisplayName("every record keeps the revision it was appended at, oldest first")
    void everyRecordKeepsItsOwnRevision() {
        String caseId = openCase();
        appendEvidence(caseId, "first");
        appendEvidence(caseId, "second");

        JsonNode answer = readInternalEvidence(caseId);

        assertThat(answer.get("input_revision").asInt()).isEqualTo(3);
        // Two records, and their versions differ: a list that reported the case's current revision for every
        // record would look right while destroying the only thing a citation can be checked against.
        List<String> versions = new java.util.ArrayList<>();
        for (JsonNode ref : answer.get("evidence")) {
            versions.add(ref.get("source_version").stringValue());
        }
        assertThat(versions).containsExactly("2", "3");
    }

    @Test
    @DisplayName("an unknown case is 404, and a user token is refused")
    void theRouteIsServiceOnlyAndScopedToACase() {
        String caseId = openCase();

        rest.get()
                .uri("/internal/v1/cases/0f5e6d7c-1111-4222-8333-444455556666/evidence")
                .header(HttpHeaders.AUTHORIZATION, "Bearer " + service())
                .exchange()
                .expectStatus()
                .isNotFound();

        // A perfectly valid *user* token is refused: material is what a run reads, and a mere login is not a
        // reason to be handed a case's evidence (docs/core-contracts.md:15).
        rest.get()
                .uri("/internal/v1/cases/" + caseId + "/evidence")
                .header(HttpHeaders.AUTHORIZATION, "Bearer " + customer())
                .exchange()
                .expectStatus()
                .isEqualTo(HttpStatus.FORBIDDEN);
    }

    @Test
    @DisplayName("the read does not change the case")
    void theReadIsReadOnly() {
        String caseId = openCase();
        appendEvidence(caseId, "material");
        Map<String, Object> before = jdbc.queryForMap(
                "SELECT input_revision, version, status FROM aftersale_case WHERE case_id = ?", caseId);

        readInternalEvidence(caseId);
        readInternalEvidence(caseId);

        Map<String, Object> after = jdbc.queryForMap(
                "SELECT input_revision, version, status FROM aftersale_case WHERE case_id = ?", caseId);
        // A read that bumped the revision would make the Agent's own investigation advance the case, and every
        // citation the run made would be stale by the time it proposed.
        assertThat(after).isEqualTo(before);
    }
}
