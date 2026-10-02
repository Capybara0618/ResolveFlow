package com.resolveflow.caseservice.casefile;

import static org.assertj.core.api.Assertions.assertThat;

import com.resolveflow.caseservice.CaseDatabaseTest;
import java.util.Map;
import java.util.UUID;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.resttestclient.autoconfigure.AutoConfigureRestTestClient;
import org.springframework.http.MediaType;
import org.springframework.test.web.servlet.client.RestTestClient;
import tools.jackson.databind.JsonNode;
import tools.jackson.databind.ObjectMapper;

@AutoConfigureRestTestClient
class MerchantWorkspaceApiTest extends CaseDatabaseTest {
    private static final ObjectMapper JSON = new ObjectMapper();

    @Autowired
    RestTestClient rest;

    String merchant, admin, worker, customer, other, bundle;

    @BeforeEach
    void prepare() {
        String suffix = UUID.randomUUID().toString().substring(0, 8);
        merchant = "M-overview-" + suffix;
        admin = "overview-admin-" + suffix;
        worker = "overview-worker-" + suffix;
        customer = "overview-customer-" + suffix;
        other = "overview-other-" + suffix;
        bundle = "overview-policy-" + suffix;
        registerTestAccount(admin, merchant, "MERCHANT_ADMIN", null);
        registerTestAccount(worker, merchant, "REVIEWER", null);
        registerTestAccount(customer, merchant, "CUSTOMER", "C-overview");
        registerTestAccount(other, merchant + "-other", "MERCHANT_ADMIN", null);
        jdbc.update(
                "INSERT INTO policy_bundle(bundle_id,merchant_id,version,manifest_hash,safety_epoch,effective_from,effective_to,imported_at,source_path) VALUES (?,?,'v1',?,1,'2026-01-01',NULL,NOW(6),'private/source')",
                bundle,
                merchant,
                "a".repeat(64));
        jdbc.update(
                "INSERT INTO policy_rule(bundle_id,rule_id,position,title,text) VALUES (?,'rule-1',0,'原始条款','退款条件与例外原文')",
                bundle);
    }

    String login(String username) {
        return JSON.readTree(rest.post()
                        .uri("/api/v1/auth/login")
                        .contentType(MediaType.APPLICATION_JSON)
                        .body(Map.of("username", username, "password", "demo-pass-1003"))
                        .exchange()
                        .expectStatus()
                        .isOk()
                        .expectBody(String.class)
                        .returnResult()
                        .getResponseBody())
                .path("access_token")
                .asText();
    }

    JsonNode get(String path, String token) {
        return JSON.readTree(rest.get()
                .uri(path)
                .header("Authorization", "Bearer " + token)
                .exchange()
                .expectStatus()
                .isOk()
                .expectBody(String.class)
                .returnResult()
                .getResponseBody());
    }

    String create(String status) {
        String id = UUID.randomUUID().toString();
        jdbc.update(
                "INSERT INTO aftersale_case(case_id,merchant_id,customer_id,order_id,line_id,description,status,input_revision,version,created_at,updated_at) VALUES (?,?,'C-overview','O-overview','L-overview','合成工单',?,1,1,NOW(6),NOW(6))",
                id,
                merchant,
                status);
        return id;
    }

    @Test
    void overviewCountsAllRowsAndDoesNotMutateCases() {
        for (int i = 0; i < 24; i++) create("PENDING_REVIEW");
        create("CLOSED_SUCCESS");
        var before = jdbc.queryForList(
                "SELECT case_id,status,version,input_revision FROM aftersale_case WHERE merchant_id=? ORDER BY case_id",
                merchant);
        var result = get("/api/v1/admin/overview", login(admin));
        assertThat(result.path("unclaimed").asLong()).isEqualTo(24);
        assertThat(result.path("coordination_total").asLong()).isEqualTo(24);
        assertThat(result.path("items").size()).isEqualTo(20);
        assertThat(result.path("enabled_staff").asLong()).isEqualTo(2);
        assertThat(result.path("mine").asLong()).isZero();
        assertThat(jdbc.queryForList(
                        "SELECT case_id,status,version,input_revision FROM aftersale_case WHERE merchant_id=? ORDER BY case_id",
                        merchant))
                .isEqualTo(before);
        assertThat(get("/api/v1/admin/overview", login(other)).path("unclaimed").asLong())
                .isZero();
    }

    @Test
    void disabledOwnerAndUnknownAreCountedOnceAndClosedIsExcluded() {
        String id = create("RECONCILING");
        jdbc.update(
                "INSERT INTO case_collaboration(case_id,owner_username,version,updated_at) VALUES (?,?,1,NOW(6))",
                id,
                worker);
        jdbc.update("UPDATE identity_account SET enabled=FALSE WHERE username=?", worker);
        String closed = create("CLOSED_REJECTED");
        jdbc.update(
                "INSERT INTO case_collaboration(case_id,owner_username,version,updated_at) VALUES (?,?,1,NOW(6))",
                closed,
                worker);
        var result = get("/api/v1/admin/overview", login(admin));
        assertThat(result.path("attention").asLong()).isEqualTo(1);
        assertThat(result.path("coordination_total").asLong()).isEqualTo(1);
        assertThat(result.path("items").get(0).path("reasons").toString())
                .contains("RESULT_UNKNOWN", "OWNER_UNAVAILABLE");
    }

    @Test
    void onlyCurrentAcceptedFailuresNeedAttentionAndMineIncludesWaiting() {
        String id = create("PENDING_REVIEW");
        jdbc.update(
                "INSERT INTO case_collaboration(case_id,owner_username,version,updated_at) VALUES (?,?,1,NOW(6))",
                id,
                admin);
        for (int i = 0; i < 2; i++)
            jdbc.update(
                    "INSERT INTO agent_callback(callback_id,case_id,run_id,input_revision,kind,disposition,payload_hash,received_at) VALUES (?,?,?,1,'FAILED','ACCEPTED',?,NOW(6))",
                    UUID.randomUUID().toString(),
                    id,
                    UUID.randomUUID().toString(),
                    "b".repeat(64));
        var result = get("/api/v1/admin/overview", login(admin));
        assertThat(result.path("attention").asLong()).isEqualTo(1);
        assertThat(result.path("mine").asLong()).isEqualTo(1);
        jdbc.update("UPDATE aftersale_case SET input_revision=2,status='WAITING_CUSTOMER' WHERE case_id=?", id);
        result = get("/api/v1/admin/overview", login(admin));
        assertThat(result.path("attention").asLong()).isZero();
        assertThat(result.path("mine").asLong()).isEqualTo(1);
    }

    @Test
    void policiesAreScopedOriginalReadOnlyProjections() {
        var list = get("/api/v1/admin/policies", login(admin));
        assertThat(list.path("items").size()).isEqualTo(1);
        assertThat(list.toString()).doesNotContain("private/source");
        var detail = get("/api/v1/admin/policies/" + bundle, login(admin));
        assertThat(detail.path("rules").get(0).path("text").asText()).isEqualTo("退款条件与例外原文");
        assertThat(detail.path("rules").get(0).path("content_hash").asText()).hasSize(64);
        rest.get()
                .uri("/api/v1/admin/policies/" + bundle)
                .header("Authorization", "Bearer " + login(other))
                .exchange()
                .expectStatus()
                .isNotFound();
        rest.get()
                .uri("/api/v1/admin/policies/missing")
                .header("Authorization", "Bearer " + login(admin))
                .exchange()
                .expectStatus()
                .isNotFound();
    }

    @Test
    void onlyCurrentMerchantAdminsMayReadManagementSurfaces() {
        for (String path :
                new String[] {"/api/v1/admin/overview", "/api/v1/admin/policies", "/api/v1/admin/policies/" + bundle}) {
            rest.get().uri(path).exchange().expectStatus().isUnauthorized();
            for (String user : new String[] {worker, customer})
                rest.get()
                        .uri(path)
                        .header("Authorization", "Bearer " + login(user))
                        .exchange()
                        .expectStatus()
                        .isForbidden();
        }
        String token = login(admin);
        jdbc.update("UPDATE identity_account SET identity_version=identity_version+1 WHERE username=?", admin);
        rest.get()
                .uri("/api/v1/admin/overview")
                .header("Authorization", "Bearer " + token)
                .exchange()
                .expectStatus()
                .isUnauthorized();
    }
}
