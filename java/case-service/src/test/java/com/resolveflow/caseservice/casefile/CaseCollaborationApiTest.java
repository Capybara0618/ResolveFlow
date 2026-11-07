package com.resolveflow.caseservice.casefile;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

import com.resolveflow.caseservice.CaseDatabaseTest;
import com.resolveflow.shared.security.AuthenticatedPrincipal;
import com.resolveflow.shared.security.JwtCodec;
import com.resolveflow.shared.security.Role;
import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.time.Instant;
import java.util.Map;
import java.util.UUID;
import java.util.concurrent.CyclicBarrier;
import java.util.concurrent.Executors;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.resttestclient.autoconfigure.AutoConfigureRestTestClient;
import org.springframework.boot.test.web.server.LocalServerPort;
import org.springframework.http.MediaType;
import org.springframework.test.web.servlet.client.RestTestClient;
import tools.jackson.databind.JsonNode;
import tools.jackson.databind.ObjectMapper;

@AutoConfigureRestTestClient
class CaseCollaborationApiTest extends CaseDatabaseTest {
    private static final ObjectMapper JSON = new ObjectMapper();

    @Autowired
    RestTestClient rest;

    @Autowired
    JwtCodec codec;

    @Autowired
    CaseCollaborationService collaborations;

    @Autowired
    AuthorizationRepository authorizations;

    @LocalServerPort
    int port;

    private String caseId;

    @BeforeEach
    void prepare() {
        deleteAllCaseData(jdbc);
        caseId = UUID.randomUUID().toString();
        jdbc.update("""
                INSERT INTO aftersale_case
                    (case_id,merchant_id,buyer_id,order_id,line_id,description,status,input_revision,version,created_at,updated_at)
                VALUES (?,'M-1001','B-legacy-60865438438feefa1dfbc0ce3d07ba2cb1b09a80',?,'collaboration-test','合成协作申请','PENDING_REVIEW',3,7,NOW(6),NOW(6))
                """, caseId, UUID.randomUUID().toString());
    }

    private String token(String username) {
        Role role = username.contains("admin")
                ? Role.MERCHANT_ADMIN
                : username.contains("customer") ? Role.CUSTOMER : Role.REVIEWER;
        String merchant = username.endsWith("m2") ? "M-1002" : "M-1001";
        return codec.issue(
                new AuthenticatedPrincipal(
                        username,
                        role == Role.CUSTOMER ? null : merchant,
                        role,
                        role == Role.CUSTOMER ? "B-legacy-60865438438feefa1dfbc0ce3d07ba2cb1b09a80" : null),
                Instant.now());
    }

    private JsonNode read(String username) {
        String body = rest.get()
                .uri("/api/v1/cases/" + caseId + "/collaboration")
                .header("Authorization", "Bearer " + token(username))
                .exchange()
                .expectStatus()
                .isOk()
                .expectBody(String.class)
                .returnResult()
                .getResponseBody();
        return JSON.readTree(body);
    }

    private JsonNode act(String username, Long version, String action, String target, int status) {
        var request = rest.post()
                .uri("/api/v1/cases/" + caseId + "/collaboration")
                .header("Authorization", "Bearer " + token(username));
        if (version != null) request.header("If-Collaboration-Match", "\"" + version + "\"");
        String body = request.contentType(MediaType.APPLICATION_JSON)
                .body(
                        target == null
                                ? Map.of("action", action, "reason", "合成协作验收")
                                : Map.of("action", action, "reason", "合成协作验收", "target_username", target))
                .exchange()
                .expectStatus()
                .isEqualTo(status)
                .expectBody(String.class)
                .returnResult()
                .getResponseBody();
        return JSON.readTree(body);
    }

    @Test
    void collaborationDoesNotChangeBusinessRevisionOrCreateInvestigation() {
        var originalCase = jdbc.queryForMap("SELECT * FROM aftersale_case WHERE case_id=?", caseId);
        assertThat(read("demo-reviewer").get("version").longValue()).isZero();
        act("demo-reviewer", 0L, "CLAIM", null, 200);
        act("demo-reviewer", 1L, "TRANSFER", "demo-reviewer-2", 200);
        act("demo-reviewer-2", 2L, "RELEASE", null, 200);
        JsonNode view = read("demo-reviewer");
        assertThat(view.get("version").longValue()).isEqualTo(3);
        assertThat(view.get("owner").isNull()).isTrue();
        assertThat(view.get("history").size()).isEqualTo(3);
        assertThat(jdbc.queryForMap("SELECT version,input_revision,status FROM aftersale_case WHERE case_id=?", caseId))
                .containsEntry("version", 7L)
                .containsEntry("input_revision", 3)
                .containsEntry("status", "PENDING_REVIEW");
        assertThat(jdbc.queryForObject("SELECT COUNT(*) FROM agent_binding", Integer.class))
                .isZero();
        assertThat(jdbc.queryForObject("SELECT COUNT(*) FROM event_outbox", Integer.class))
                .isZero();
        assertThat(jdbc.queryForObject("SELECT COUNT(*) FROM case_timeline", Integer.class))
                .isZero();
        assertThat(jdbc.queryForMap("SELECT * FROM aftersale_case WHERE case_id=?", caseId))
                .isEqualTo(originalCase);
    }

    @Test
    void repeatClaimIsIdempotentButOldOwnerCannotActAfterTransferOrAba() {
        act("demo-reviewer", 0L, "CLAIM", null, 200);
        assertThat(act("demo-reviewer", 0L, "CLAIM", null, 200).get("version").longValue())
                .isEqualTo(1);
        act("demo-reviewer-2", 0L, "CLAIM", null, 409);
        act("demo-reviewer-2", 1L, "RELEASE", null, 409);
        act("demo-reviewer-2", 1L, "TRANSFER", "demo-admin", 409);
        act("demo-reviewer", 1L, "TRANSFER", "demo-reviewer-2", 200);
        act("demo-reviewer", 1L, "RELEASE", null, 409);
        act("demo-reviewer-2", 2L, "TRANSFER", "demo-reviewer", 200);
        act("demo-reviewer", 1L, "RELEASE", null, 409);
        assertThat(read("demo-reviewer").get("history").size()).isEqualTo(3);
    }

    @Test
    void administratorMustExplicitlyTakeOverAndCannotImplicitlyClaimOccupiedCase() {
        act("demo-reviewer", 0L, "CLAIM", null, 200);
        act("demo-admin", 1L, "CLAIM", null, 409);
        act("demo-reviewer-2", 1L, "TAKEOVER", null, 403);
        act("demo-admin", 1L, "TAKEOVER", null, 200);
        assertThat(read("demo-admin").get("owner").get("username").stringValue())
                .isEqualTo("demo-admin");
        act("demo-reviewer", 1L, "TRANSFER", "demo-reviewer-2", 409);
    }

    @Test
    void crossMerchantAndCustomerCannotReadOrAssign() {
        for (String username : new String[] {"demo-reviewer-m2", "demo-admin-m2"}) {
            rest.get()
                    .uri("/api/v1/cases/" + caseId + "/collaboration")
                    .header("Authorization", "Bearer " + token(username))
                    .exchange()
                    .expectStatus()
                    .isNotFound();
            act(username, 0L, "CLAIM", null, 404);
        }
        act("demo-customer", 0L, "CLAIM", null, 403);
        rest.get()
                .uri("/api/v1/cases/" + caseId + "/collaboration")
                .header("Authorization", "Bearer " + token("demo-customer"))
                .exchange()
                .expectStatus()
                .isForbidden();
    }

    @Test
    void targetsMustBeEnabledStaffOfSameMerchant() {
        act("demo-reviewer", 0L, "CLAIM", null, 200);
        for (String target : new String[] {"demo-customer", "demo-reviewer-m2", "missing-staff"}) {
            act("demo-reviewer", 1L, "TRANSFER", target, 422);
        }
        jdbc.update("UPDATE identity_account SET enabled=FALSE WHERE username='demo-reviewer-2'");
        try {
            act("demo-reviewer", 1L, "TRANSFER", "demo-reviewer-2", 422);
        } finally {
            jdbc.update("UPDATE identity_account SET enabled=TRUE WHERE username='demo-reviewer-2'");
        }
        assertThat(read("demo-reviewer").get("version").longValue()).isEqualTo(1);
    }

    @Test
    void disabledOwnerRemainsVisibleAndAdministratorCanRelease() {
        act("demo-reviewer", 0L, "CLAIM", null, 200);
        jdbc.update("UPDATE identity_account SET enabled=FALSE WHERE username='demo-reviewer'");
        try {
            assertThat(read("demo-admin").get("owner").get("enabled").booleanValue())
                    .isFalse();
            act("demo-reviewer", 1L, "RELEASE", null, 401);
            act("demo-admin", 1L, "RELEASE", null, 200);
        } finally {
            jdbc.update("UPDATE identity_account SET enabled=TRUE WHERE username='demo-reviewer'");
        }
    }

    @Test
    void waitingForCustomerKeepsOwnerButExecutingAndTerminalCannotBeReassigned() {
        act("demo-reviewer", 0L, "CLAIM", null, 200);
        jdbc.update("UPDATE aftersale_case SET status='WAITING_CUSTOMER',input_revision=4 WHERE case_id=?", caseId);
        assertThat(read("demo-reviewer").get("owner").get("username").stringValue())
                .isEqualTo("demo-reviewer");
        for (String status :
                new String[] {"AUTHORIZED", "EXECUTING", "RECONCILING", "CLOSED_SUCCESS", "CLOSED_REJECTED", "CANCELLED"
                }) {
            jdbc.update("UPDATE aftersale_case SET status=? WHERE case_id=?", status, caseId);
            act("demo-admin", 1L, "TAKEOVER", null, 409);
            assertThat(read("demo-admin").get("owner").get("username").stringValue())
                    .isEqualTo("demo-reviewer");
        }
    }

    @Test
    void missingOrStaleVersionAndInvalidActionAreRejected() {
        act("demo-reviewer", null, "CLAIM", null, 409);
        act("demo-reviewer", 9L, "CLAIM", null, 409);
        act("demo-reviewer", 0L, "APPROVE", null, 422);
        assertThat(read("demo-reviewer").get("history").size()).isZero();
    }

    @Test
    void simultaneousClaimsHaveOneWinnerAndOneAuditEvent() throws Exception {
        var barrier = new CyclicBarrier(2);
        try (var executor = Executors.newVirtualThreadPerTaskExecutor()) {
            var first = executor.submit(() -> concurrentClaim("demo-reviewer", barrier));
            var second = executor.submit(() -> concurrentClaim("demo-reviewer-2", barrier));
            assertThat(new int[] {first.get(), second.get()}).containsExactlyInAnyOrder(200, 409);
        }
        JsonNode view = read("demo-admin");
        assertThat(view.get("version").longValue()).isEqualTo(1);
        assertThat(view.get("history").size()).isEqualTo(1);
    }

    @Test
    void transactionRechecksCapturedSessionVersionAfterPasswordReset() {
        var principal = new AuthenticatedPrincipal("demo-reviewer", "M-1001", Role.REVIEWER, null);
        long captured = jdbc.queryForObject(
                "SELECT identity_version FROM identity_account WHERE username='demo-reviewer'", Long.class);
        jdbc.update("UPDATE identity_account SET identity_version=identity_version+1 WHERE username='demo-reviewer'");
        try {
            assertThatThrownBy(() -> collaborations.act(
                            principal,
                            captured,
                            caseId,
                            "\"0\"",
                            new CaseCollaborationService.Action("CLAIM", null, "旧会话提交")))
                    .isInstanceOf(
                            com.resolveflow.caseservice.order.RequestPrincipalResolver.UnauthenticatedException.class);
            assertThat(read("demo-admin").get("history").size()).isZero();
        } finally {
            jdbc.update("UPDATE identity_account SET identity_version=? WHERE username='demo-reviewer'", captured);
        }
    }

    @Test
    void consumedAuthorizationFreezesAssignmentEvenWhenCaseReturnsToPendingReview() {
        act("demo-reviewer", 0L, "CLAIM", null, 200);
        String proposal = UUID.randomUUID().toString();
        jdbc.update("""
                INSERT INTO case_proposal
                    (proposal_id,case_id,run_id,input_revision,sequence,status,payload,payload_hash,created_at)
                VALUES (?,?,?,3,1,'VALIDATED','{}',?,NOW(6))
                """, proposal, caseId, UUID.randomUUID().toString(), "a".repeat(64));
        Instant now = Instant.now();
        String authorizationId = UUID.randomUUID().toString();
        authorizations.insert(
                authorizationId,
                caseId,
                1,
                "PENDING_REVIEW",
                "REFUND",
                3,
                proposal,
                UUID.randomUUID().toString(),
                "a".repeat(64),
                32900,
                1,
                "CNY",
                "v1",
                null,
                now,
                now);
        assertThat(authorizations.decide(authorizationId, 1, "APPROVED", "demo-reviewer", "REVIEWER", "合成已批准", now))
                .isEqualTo(1);
        assertThat(authorizations.consume(authorizationId, 2, now)).isEqualTo(1);
        act("demo-admin", 1L, "RELEASE", null, 409);
        act("demo-admin", 1L, "TAKEOVER", null, 409);
        assertThat(read("demo-admin").get("allowed_actions").size()).isZero();
        assertThat(read("demo-admin").get("version").longValue()).isEqualTo(1);
    }

    private int concurrentClaim(String username, CyclicBarrier barrier) throws Exception {
        String token = token(username);
        HttpRequest request = HttpRequest.newBuilder(
                        URI.create("http://127.0.0.1:" + port + "/api/v1/cases/" + caseId + "/collaboration"))
                .header("Authorization", "Bearer " + token)
                .header("Content-Type", "application/json")
                .header("If-Collaboration-Match", "\"0\"")
                .POST(HttpRequest.BodyPublishers.ofString("{\"action\":\"CLAIM\",\"reason\":\"并发领取\"}"))
                .build();
        barrier.await();
        try (var client = HttpClient.newHttpClient()) {
            return client.send(request, HttpResponse.BodyHandlers.ofString()).statusCode();
        }
    }
}
