package com.resolveflow.caseservice.casefile;

import static org.assertj.core.api.Assertions.assertThat;

import com.resolveflow.caseservice.CaseDatabaseTest;
import com.resolveflow.shared.security.AuthenticatedPrincipal;
import com.resolveflow.shared.security.JwtCodec;
import com.resolveflow.shared.security.Role;
import java.time.Duration;
import java.time.Instant;
import java.util.Map;
import java.util.UUID;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.ValueSource;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.boot.resttestclient.autoconfigure.AutoConfigureRestTestClient;
import org.springframework.boot.test.context.TestConfiguration;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Primary;
import org.springframework.http.MediaType;
import org.springframework.test.web.servlet.client.RestTestClient;
import tools.jackson.databind.JsonNode;
import tools.jackson.databind.ObjectMapper;

@AutoConfigureRestTestClient
class ReviewerOwnershipApiTest extends CaseDatabaseTest {
    private static final ObjectMapper JSON = new ObjectMapper();

    @Autowired
    RestTestClient rest;

    @Autowired
    JwtCodec codec;

    @Autowired
    OwnedCommerce commerce;

    private String caseId;
    private String evidenceId;

    @TestConfiguration
    static class Configuration {
        @Bean
        @Primary
        OwnedCommerce commerce(
                org.springframework.web.client.RestClient.Builder builder,
                @Value("${resolveflow.identity.jwt.secret}") String secret) {
            return new OwnedCommerce(builder, new JwtCodec(secret, Duration.ofHours(1)));
        }
    }

    static class OwnedCommerce extends StubCommerce {
        volatile boolean networkInsideTransaction;
        volatile Runnable duringRead;

        OwnedCommerce(org.springframework.web.client.RestClient.Builder builder, JwtCodec codec) {
            super(builder, codec);
        }

        @Override
        public java.util.Optional<LineContext> readLineContext(String lineId) {
            networkInsideTransaction |=
                    org.springframework.transaction.support.TransactionSynchronizationManager
                            .isActualTransactionActive();
            if (duringRead != null) duringRead.run();
            return super.readLineContext(lineId);
        }
    }

    private String token(String username) {
        Role role = username.contains("admin")
                ? Role.MERCHANT_ADMIN
                : username.contains("customer") ? Role.CUSTOMER : Role.REVIEWER;
        return codec.issue(
                new AuthenticatedPrincipal(username, "M-1001", role, role == Role.CUSTOMER ? "C-2002" : null),
                Instant.now());
    }

    @BeforeEach
    void prepare() {
        deleteAllCaseData(jdbc);
        commerce.reset();
        commerce.networkInsideTransaction = false;
        commerce.duringRead = null;
        var created = post(
                "demo-customer",
                "/api/v1/cases",
                null,
                null,
                Map.of("line_id", "7001", "description", "合成多人审核验收", "requested_actions", new String[] {"REFUND"}),
                201);
        caseId = created.get("case_id").stringValue();
        post(
                "demo-customer",
                path("evidence"),
                null,
                null,
                Map.of("text", "本人未收到包裹", "evidence_kind", "CUSTOMER_STATEMENT"),
                200);
        evidenceId = jdbc.queryForObject(
                "SELECT evidence_id FROM case_evidence WHERE case_id=? LIMIT 1", String.class, caseId);
        jdbc.update("UPDATE aftersale_case SET status='PENDING_REVIEW' WHERE case_id=?", caseId);
    }

    private String path(String endpoint) {
        return "/api/v1/cases/" + caseId + "/" + endpoint;
    }

    private long version() {
        return jdbc.queryForObject("SELECT version FROM aftersale_case WHERE case_id=?", Long.class, caseId);
    }

    private JsonNode post(
            String username, String path, Long caseVersion, Long collaborationVersion, Object body, int status) {
        var request = rest.post()
                .uri(path)
                .header("Authorization", "Bearer " + token(username))
                .header("Idempotency-Key", UUID.randomUUID().toString());
        if (caseVersion != null) request.header("If-Match", "\"" + caseVersion + "\"");
        if (collaborationVersion != null) request.header("If-Collaboration-Match", "\"" + collaborationVersion + "\"");
        return JSON.readTree(request.contentType(MediaType.APPLICATION_JSON)
                .body(body)
                .exchange()
                .expectStatus()
                .isEqualTo(status)
                .expectBody(String.class)
                .returnResult()
                .getResponseBody());
    }

    @Test
    void transferDirectoryContainsOnlyEnabledStaffInCurrentMerchant() {
        String answer = rest.get()
                .uri("/api/v1/review/staff")
                .header("Authorization", "Bearer " + token("demo-reviewer"))
                .exchange()
                .expectStatus()
                .isOk()
                .expectBody(String.class)
                .returnResult()
                .getResponseBody();
        assertThat(answer)
                .contains("demo-reviewer-2", "demo-admin")
                .doesNotContain("password", "customer", "demo-reviewer-m2");
        jdbc.update("UPDATE identity_account SET enabled=FALSE WHERE username='demo-reviewer-2'");
        try {
            String disabled = rest.get()
                    .uri("/api/v1/review/staff")
                    .header("Authorization", "Bearer " + token("demo-reviewer"))
                    .exchange()
                    .expectStatus()
                    .isOk()
                    .expectBody(String.class)
                    .returnResult()
                    .getResponseBody();
            assertThat(disabled).doesNotContain("demo-reviewer-2");
            rest.get()
                    .uri("/api/v1/review/staff")
                    .header("Authorization", "Bearer " + token("demo-customer"))
                    .exchange()
                    .expectStatus()
                    .isForbidden();
        } finally {
            jdbc.update("UPDATE identity_account SET enabled=TRUE WHERE username='demo-reviewer-2'");
        }
    }

    private void claim(String username, long version) {
        post(username, path("collaboration"), null, version, Map.of("action", "CLAIM", "reason", "领取验收"), 200);
    }

    private Object body(String endpoint) {
        return switch (endpoint) {
            case "review-actions" -> Map.of("action", "REJECT", "reason", "人工拒绝验收");
            case "reviewed-evidence" ->
                Map.of("source_evidence_id", evidenceId, "verification_result", "CONFIRMED", "reason", "人工核验验收");
            case "evidence" -> Map.of("text", "人工记录验收", "evidence_kind", "REVIEWER_VERIFICATION");
            case "cancel" -> Map.of("reason", "工作人员取消验收");
            case "reviews" ->
                Map.of(
                        "authorization_id",
                        UUID.randomUUID().toString(),
                        "authorization_version",
                        1,
                        "decision",
                        "REJECT",
                        "reason",
                        "审核验收");
            case "manual-proposals" -> manualBody();
            default -> throw new IllegalArgumentException(endpoint);
        };
    }

    private Map<String, Object> manualBody() {
        String context = rest.get()
                .uri(path("review-context"))
                .header("Authorization", "Bearer " + token("demo-reviewer"))
                .exchange()
                .expectStatus()
                .isOk()
                .expectBody(String.class)
                .returnResult()
                .getResponseBody();
        JsonNode rule = JSON.readTree(context).get("policy_rules").get(0);
        var material = jdbc.queryForMap(
                "SELECT source_ref,source_version,content_hash FROM case_evidence WHERE evidence_id=?", evidenceId);
        return Map.of(
                "action",
                "REFUND",
                "reason",
                "人工全额退款验收",
                "evidence_refs",
                new Object[] {
                    Map.of(
                            "observation_id",
                            evidenceId,
                            "source_ref",
                            material.get("source_ref"),
                            "source_version",
                            material.get("source_version"),
                            "content_hash",
                            material.get("content_hash"))
                },
                "policy_refs",
                new Object[] {
                    Map.of(
                            "bundle_id",
                            rule.get("bundle_id").stringValue(),
                            "version",
                            rule.get("version").stringValue(),
                            "rule_id",
                            rule.get("rule_id").stringValue(),
                            "chunk_id",
                            rule.get("chunk_id").stringValue(),
                            "content_hash",
                            rule.get("content_hash").stringValue())
                });
    }

    @ParameterizedTest
    @ValueSource(strings = {"review-actions", "reviewed-evidence", "evidence", "cancel", "reviews", "manual-proposals"})
    void everyLegacyHumanRouteRequiresOwnershipAndCollaborationVersion(String endpoint) {
        var original = jdbc.queryForMap("SELECT * FROM aftersale_case WHERE case_id=?", caseId);
        post("demo-reviewer", path(endpoint), version(), null, body(endpoint), 409);
        assertThat(jdbc.queryForMap("SELECT * FROM aftersale_case WHERE case_id=?", caseId))
                .isEqualTo(original);
    }

    @ParameterizedTest
    @ValueSource(strings = {"review-actions", "reviewed-evidence", "evidence", "cancel", "reviews", "manual-proposals"})
    void nonOwnerAndTransferredOldPageCannotUseAnyHumanRoute(String endpoint) {
        claim("demo-reviewer", 0);
        long caseVersion = version();
        post("demo-reviewer-2", path(endpoint), caseVersion, 1L, body(endpoint), 409);
        post(
                "demo-reviewer",
                path("collaboration"),
                null,
                1L,
                Map.of("action", "TRANSFER", "target_username", "demo-reviewer-2", "reason", "转交验收"),
                200);
        post("demo-reviewer", path(endpoint), caseVersion, 1L, body(endpoint), 409);
        assertThat(version()).isEqualTo(caseVersion);
    }

    @Test
    void ownerMayRejectButStaleBusinessVersionCannotBeUsed() {
        claim("demo-reviewer", 0);
        post("demo-reviewer", path("review-actions"), version() - 1, 1L, body("review-actions"), 409);
        post("demo-reviewer", path("review-actions"), version(), 1L, body("review-actions"), 200);
        assertThat(jdbc.queryForObject("SELECT status FROM aftersale_case WHERE case_id=?", String.class, caseId))
                .isEqualTo("CLOSED_REJECTED");
    }

    @Test
    void administratorRequiresExplicitTakeoverBeforeVerification() {
        claim("demo-reviewer", 0);
        post("demo-admin", path("reviewed-evidence"), version(), 1L, body("reviewed-evidence"), 409);
        post("demo-admin", path("collaboration"), null, 1L, Map.of("action", "TAKEOVER", "reason", "管理员接管验收"), 200);
        post("demo-admin", path("reviewed-evidence"), version(), 2L, body("reviewed-evidence"), 200);
        assertThat(jdbc.queryForObject(
                        "SELECT appended_role FROM case_evidence WHERE reviewed_evidence_id=?",
                        String.class,
                        evidenceId))
                .isEqualTo("MERCHANT_ADMIN");
        post("demo-admin", path("manual-proposals"), version(), 2L, manualBody(), 200);
        assertThat(jdbc.queryForObject("SELECT authored_role FROM case_proposal WHERE case_id=?", String.class, caseId))
                .isEqualTo("MERCHANT_ADMIN");
        var authorization = jdbc.queryForMap(
                "SELECT authorization_id,authorization_version FROM case_authorization WHERE case_id=?", caseId);
        post(
                "demo-admin",
                path("reviews"),
                version(),
                2L,
                Map.of(
                        "authorization_id",
                        authorization.get("authorization_id"),
                        "authorization_version",
                        authorization.get("authorization_version"),
                        "decision",
                        "APPROVE",
                        "reason",
                        "管理员人工批准验收"),
                200);
        assertThat(jdbc.queryForObject(
                        "SELECT decided_role FROM case_authorization WHERE case_id=?", String.class, caseId))
                .isEqualTo("MERCHANT_ADMIN");
        assertThat(commerce.networkInsideTransaction).isFalse();
    }

    @Test
    void transferDuringNetworkPreflightSucceedsAndOldProposalCannotCommit() throws Exception {
        claim("demo-reviewer", 0);
        var request = manualBody();
        long seen = version();
        var entered = new java.util.concurrent.CountDownLatch(1);
        var release = new java.util.concurrent.CountDownLatch(1);
        commerce.duringRead = () -> {
            entered.countDown();
            try {
                if (!release.await(10, java.util.concurrent.TimeUnit.SECONDS))
                    throw new IllegalStateException("preflight release timed out");
            } catch (InterruptedException e) {
                Thread.currentThread().interrupt();
                throw new IllegalStateException(e);
            }
        };
        try (var executor = java.util.concurrent.Executors.newVirtualThreadPerTaskExecutor()) {
            var proposal =
                    executor.submit(() -> post("demo-reviewer", path("manual-proposals"), seen, 1L, request, 409));
            try {
                assertThat(entered.await(10, java.util.concurrent.TimeUnit.SECONDS))
                        .isTrue();
                post(
                        "demo-reviewer",
                        path("collaboration"),
                        null,
                        1L,
                        Map.of("action", "TRANSFER", "target_username", "demo-reviewer-2", "reason", "网络复核期间转交"),
                        200);
            } finally {
                release.countDown();
            }
            proposal.get(10, java.util.concurrent.TimeUnit.SECONDS);
        } finally {
            commerce.duringRead = null;
        }
        assertThat(commerce.networkInsideTransaction).isFalse();
        assertThat(jdbc.queryForObject("SELECT COUNT(*) FROM case_proposal WHERE case_id=?", Integer.class, caseId))
                .isZero();
        assertThat(version()).isEqualTo(seen);
    }
}
