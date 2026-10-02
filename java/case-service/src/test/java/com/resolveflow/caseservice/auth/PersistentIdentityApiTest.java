package com.resolveflow.caseservice.auth;

import static org.assertj.core.api.Assertions.assertThat;

import com.resolveflow.caseservice.CaseDatabaseTest;
import com.resolveflow.shared.security.AuthenticatedPrincipal;
import com.resolveflow.shared.security.JwtCodec;
import com.resolveflow.shared.security.Role;
import java.time.Instant;
import java.util.Map;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.resttestclient.autoconfigure.AutoConfigureRestTestClient;
import org.springframework.http.MediaType;
import org.springframework.test.web.servlet.client.RestTestClient;
import tools.jackson.databind.ObjectMapper;

@AutoConfigureRestTestClient
class PersistentIdentityApiTest extends CaseDatabaseTest {
    private static final ObjectMapper JSON = new ObjectMapper();

    @Autowired
    RestTestClient rest;

    @Autowired
    JwtCodec codec;

    @AfterEach
    void restoreAccounts() {
        jdbc.update(
                "UPDATE identity_account SET enabled=TRUE, identity_version=0 WHERE username IN (?,?)",
                "demo-reviewer",
                "demo-customer");
        jdbc.update("DELETE FROM identity_account WHERE username='db-only-reviewer'");
        jdbc.update("UPDATE identity_merchant SET enabled=TRUE WHERE merchant_id='M-1001'");
    }

    private String login(String username, String password) {
        String body = rest.post()
                .uri("/api/v1/auth/login")
                .contentType(MediaType.APPLICATION_JSON)
                .body(Map.of("username", username, "password", password))
                .exchange()
                .expectStatus()
                .isOk()
                .expectBody(String.class)
                .returnResult()
                .getResponseBody();
        return JSON.readTree(body).get("access_token").stringValue();
    }

    @Test
    void correctlySignedButUnknownOrMisboundUsersAreRejected() {
        for (var principal : new AuthenticatedPrincipal[] {
            new AuthenticatedPrincipal("unknown-account", "M-1001", Role.REVIEWER, null),
            new AuthenticatedPrincipal("demo-reviewer", "M-1002", Role.REVIEWER, null),
            new AuthenticatedPrincipal("demo-customer", "M-1001", Role.CUSTOMER, "C-2003")
        }) {
            rest.get()
                    .uri("/api/v1/auth/me")
                    .header("Authorization", "Bearer " + codec.issue(principal, Instant.now()))
                    .exchange()
                    .expectStatus()
                    .isUnauthorized();
        }
    }

    @Test
    void administratorCannotBypassMissingCaseVisibilityOrInvalidProposal() {
        String token = login("demo-admin", "demo-pass-1100");
        rest.get()
                .uri("/api/v1/review/cases")
                .header("Authorization", "Bearer " + token)
                .exchange()
                .expectStatus()
                .isOk();
        String caseId = "00000000-0000-4000-8000-00000000eeee";
        // Admin is a staff role; missing cases remain invisible. Real owner/takeover is covered in
        // ReviewerOwnershipApiTest.
        for (String endpoint : new String[] {"review-actions", "cancel", "reviewed-evidence"}) {
            Map<String, Object> body = endpoint.equals("reviewed-evidence")
                    ? Map.of("source_evidence_id", caseId, "verification_result", "CONFIRMED", "reason", "核验")
                    : endpoint.equals("review-actions")
                            ? Map.of("action", "REJECT", "reason", "拒绝")
                            : Map.of("reason", "撤销");
            rest.post()
                    .uri("/api/v1/cases/" + caseId + "/" + endpoint)
                    .header("Authorization", "Bearer " + token)
                    .header("If-Match", "\"1\"")
                    .contentType(MediaType.APPLICATION_JSON)
                    .body(body)
                    .exchange()
                    .expectStatus()
                    .isNotFound();
        }
        rest.post()
                .uri("/api/v1/cases/" + caseId + "/reviews")
                .header("Authorization", "Bearer " + token)
                .header("If-Match", "\"1\"")
                .contentType(MediaType.APPLICATION_JSON)
                .body(Map.of(
                        "authorization_id", caseId, "authorization_version", 1, "decision", "APPROVE", "reason", "批准"))
                .exchange()
                .expectStatus()
                .isNotFound();
        rest.post()
                .uri("/api/v1/cases/" + caseId + "/manual-proposals")
                .header("Authorization", "Bearer " + token)
                .contentType(MediaType.APPLICATION_JSON)
                .body(Map.of(
                        "action",
                        "REFUND",
                        "evidence_refs",
                        new Object[] {},
                        "policy_refs",
                        new Object[] {},
                        "reason",
                        "人工方案"))
                .exchange()
                .expectStatus()
                .isEqualTo(422);
    }

    @Test
    void accountCreatedInDatabaseCanLoginWithoutChangingJavaSeeds() {
        jdbc.update(
                "INSERT INTO identity_account (username,merchant_id,role,display_name,password_hash,enabled,identity_version) "
                        + "SELECT 'db-only-reviewer',merchant_id,role,'数据库审核员',password_hash,TRUE,0 "
                        + "FROM identity_account WHERE username='demo-reviewer'");
        String token = login("db-only-reviewer", "demo-pass-1003");
        rest.get()
                .uri("/api/v1/auth/me")
                .header("Authorization", "Bearer " + token)
                .exchange()
                .expectStatus()
                .isOk()
                .expectBody(String.class)
                .value(body -> {
                    var view = JSON.readTree(body);
                    assertThat(view.get("display_name").stringValue()).isEqualTo("数据库审核员");
                    assertThat(view.get("merchant_id").stringValue()).isEqualTo("M-1001");
                    assertThat(body).doesNotContain("password_hash", "pbkdf2");
                });
    }

    @Test
    void disablingAccountInvalidatesAlreadyIssuedTokenOnBusinessAndIdentityRoutes() {
        String token = login("demo-reviewer", "demo-pass-1003");
        jdbc.update(
                "UPDATE identity_account SET enabled=FALSE,identity_version=identity_version+1 WHERE username='demo-reviewer'");
        for (String path : new String[] {"/api/v1/auth/me", "/api/v1/review/cases", "/api/v1/orders"}) {
            rest.get()
                    .uri(path)
                    .header("Authorization", "Bearer " + token)
                    .exchange()
                    .expectStatus()
                    .isUnauthorized();
        }
        rest.post()
                .uri("/api/v1/auth/login")
                .contentType(MediaType.APPLICATION_JSON)
                .body(Map.of("username", "demo-reviewer", "password", "demo-pass-1003"))
                .exchange()
                .expectStatus()
                .isUnauthorized();
    }

    @Test
    void enablingAccountAgainDoesNotReviveOldToken() {
        String old = login("demo-reviewer", "demo-pass-1003");
        jdbc.update("UPDATE identity_account SET identity_version=identity_version+2 WHERE username='demo-reviewer'");
        rest.get()
                .uri("/api/v1/auth/me")
                .header("Authorization", "Bearer " + old)
                .exchange()
                .expectStatus()
                .isUnauthorized();
        String current = login("demo-reviewer", "demo-pass-1003");
        rest.get()
                .uri("/api/v1/auth/me")
                .header("Authorization", "Bearer " + current)
                .exchange()
                .expectStatus()
                .isOk();
    }

    @Test
    void roleChangeWithoutVersionBumpStillRefusesOldPrivileges() {
        String token = login("demo-reviewer", "demo-pass-1003");
        jdbc.update("UPDATE identity_account SET role='MERCHANT_ADMIN' WHERE username='demo-reviewer'");
        try {
            rest.get()
                    .uri("/api/v1/review/cases")
                    .header("Authorization", "Bearer " + token)
                    .exchange()
                    .expectStatus()
                    .isUnauthorized();
        } finally {
            jdbc.update("UPDATE identity_account SET role='REVIEWER' WHERE username='demo-reviewer'");
        }
    }

    @Test
    void disabledMerchantCannotUseAnExistingCustomerSession() {
        String token = login("demo-customer", "demo-pass-1001");
        jdbc.update("UPDATE identity_merchant SET enabled=FALSE WHERE merchant_id='M-1001'");
        rest.get()
                .uri("/api/v1/auth/me")
                .header("Authorization", "Bearer " + token)
                .exchange()
                .expectStatus()
                .isUnauthorized();
    }

    @Test
    void eachActiveDemoMerchantHasTwoCustomersTwoReviewersAndAnAdministrator() {
        for (String merchant : new String[] {"M-1001", "M-1002"}) {
            assertThat(jdbc.queryForObject(
                            "SELECT COUNT(*) FROM identity_account WHERE merchant_id=? AND role='CUSTOMER'",
                            Integer.class,
                            merchant))
                    .isGreaterThanOrEqualTo(2);
            assertThat(jdbc.queryForObject(
                            "SELECT COUNT(*) FROM identity_account WHERE merchant_id=? AND role='REVIEWER'",
                            Integer.class,
                            merchant))
                    .isGreaterThanOrEqualTo(2);
            assertThat(jdbc.queryForObject(
                            "SELECT COUNT(*) FROM identity_account WHERE merchant_id=? AND role='MERCHANT_ADMIN'",
                            Integer.class,
                            merchant))
                    .isEqualTo(1);
        }
        String token = login("demo-admin", "demo-pass-1100");
        rest.get()
                .uri("/api/v1/auth/me")
                .header("Authorization", "Bearer " + token)
                .exchange()
                .expectStatus()
                .isOk()
                .expectBody(String.class)
                .value(body -> assertThat(JSON.readTree(body).get("role").stringValue())
                        .isEqualTo("MERCHANT_ADMIN"));
    }
}
