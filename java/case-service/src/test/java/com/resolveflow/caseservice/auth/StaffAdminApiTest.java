package com.resolveflow.caseservice.auth;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

import com.resolveflow.caseservice.CaseDatabaseTest;
import com.resolveflow.caseservice.order.RequestPrincipalResolver;
import java.util.Map;
import java.util.UUID;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.Executors;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.TimeoutException;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.resttestclient.autoconfigure.AutoConfigureRestTestClient;
import org.springframework.http.MediaType;
import org.springframework.test.web.servlet.client.RestTestClient;
import org.springframework.transaction.PlatformTransactionManager;
import org.springframework.transaction.support.TransactionTemplate;
import tools.jackson.databind.JsonNode;
import tools.jackson.databind.ObjectMapper;

@AutoConfigureRestTestClient
class StaffAdminApiTest extends CaseDatabaseTest {
    private static final ObjectMapper JSON = new ObjectMapper();

    @Autowired
    RestTestClient rest;

    @Autowired
    StaffAdminService staff;

    @Autowired
    RequestPrincipalResolver principals;

    @Autowired
    PlatformTransactionManager transactions;

    private void clear() {
        jdbc.update("DELETE FROM aftersale_case WHERE merchant_id='M-personnel'");
        if (jdbc.queryForObject(
                        "SELECT COUNT(*) FROM information_schema.tables WHERE table_schema=DATABASE() AND table_name='identity_account_audit'",
                        Long.class)
                > 0)
            jdbc.update("DELETE FROM identity_account_audit WHERE merchant_id IN ('M-personnel','M-personnel-other')");
        jdbc.update("DELETE FROM identity_account WHERE merchant_id IN ('M-personnel','M-personnel-other')");
    }

    @BeforeEach
    void prepare() {
        clear();
        registerTestAccount("personnel-admin", "M-personnel", "MERCHANT_ADMIN", null);
        registerTestAccount("personnel-admin2", "M-personnel", "MERCHANT_ADMIN", null);
        registerTestAccount("personnel-worker", "M-personnel", "REVIEWER", null);
        registerTestAccount("personnel-customer", "M-personnel", "CUSTOMER", "C-personnel");
        registerTestAccount("personnel-other-admin", "M-personnel-other", "MERCHANT_ADMIN", null);
    }

    @AfterEach
    void cleanup() {
        clear();
    }

    private String login(String username, String password) {
        return JSON.readTree(rest.post()
                        .uri("/api/v1/auth/login")
                        .contentType(MediaType.APPLICATION_JSON)
                        .body(Map.of("username", username, "password", password))
                        .exchange()
                        .expectStatus()
                        .isOk()
                        .expectBody(String.class)
                        .returnResult()
                        .getResponseBody())
                .get("access_token")
                .stringValue();
    }

    private String token(String username) {
        return login(username, "demo-pass-1003");
    }

    private JsonNode read(String token, String suffix) {
        return JSON.readTree(rest.get()
                .uri("/api/v1/admin/accounts" + suffix)
                .header("Authorization", "Bearer " + token)
                .exchange()
                .expectStatus()
                .isOk()
                .expectBody(String.class)
                .returnResult()
                .getResponseBody());
    }

    private JsonNode post(String token, String path, String version, Map<String, Object> body, int expected) {
        var request = rest.post().uri("/api/v1/admin/accounts" + path).header("Authorization", "Bearer " + token);
        if (version != null) request.header("If-Match", version);
        return JSON.readTree(request.contentType(MediaType.APPLICATION_JSON)
                .body(body)
                .exchange()
                .expectStatus()
                .isEqualTo(expected)
                .expectBody(String.class)
                .returnResult()
                .getResponseBody());
    }

    private Map<String, Object> update(String role, boolean enabled, String name) {
        return Map.of("role", role, "enabled", enabled, "display_name", name, "reason", "合成账号维护验收");
    }

    @Test
    void administratorListsOnlyItsMerchantWithRealPaginationAndNoCredentials() {
        String admin = token("personnel-admin");
        JsonNode first = read(admin, "?limit=1");
        assertThat(first.get("total").longValue()).isEqualTo(4);
        assertThat(first.get("current_username").stringValue()).isEqualTo("personnel-admin");
        assertThat(first.get("enabled_admins").longValue()).isEqualTo(2);
        assertThat(first.get("items").size()).isEqualTo(1);
        String cursor = first.at("/page/next_cursor").stringValue();
        JsonNode next = read(admin, "?limit=1&cursor=" + cursor);
        assertThat(next.at("/items/0/username").stringValue())
                .isNotEqualTo(first.at("/items/0/username").stringValue());
        String all = read(admin, "?limit=100").toString();
        assertThat(all).doesNotContain("personnel-other-admin", "password", "hash", "identity_version");
        assertThat(read(admin, "?role=REVIEWER&query=worker").get("total").longValue())
                .isEqualTo(1);
        for (String params : new String[] {"role=MERCHANT_ADMIN", "query=different", "status=DISABLED"})
            rest.get()
                    .uri("/api/v1/admin/accounts?" + params + "&cursor=" + cursor)
                    .header("Authorization", "Bearer " + admin)
                    .exchange()
                    .expectStatus()
                    .isBadRequest();
        rest.get()
                .uri("/api/v1/admin/accounts?cursor=" + cursor)
                .header("Authorization", "Bearer " + token("personnel-admin2"))
                .exchange()
                .expectStatus()
                .isBadRequest();
    }

    @Test
    void ordinaryStaffCustomerAndOtherMerchantCannotManageAccounts() {
        for (String user : new String[] {"personnel-worker", "personnel-customer"}) {
            String token = token(user);
            rest.get()
                    .uri("/api/v1/admin/accounts")
                    .header("Authorization", "Bearer " + token)
                    .exchange()
                    .expectStatus()
                    .isForbidden();
            post(token, "/personnel-admin", "\"1\"", update("REVIEWER", false, "越权"), 403);
        }
        String admin = token("personnel-admin");
        for (String target : new String[] {"personnel-other-admin", "missing"}) {
            post(admin, "/" + target, "\"1\"", update("REVIEWER", false, "越权"), 404);
            post(admin, "/" + target + "/password", "\"1\"", Map.of("password", "new-password", "reason", "重置"), 404);
            rest.get()
                    .uri("/api/v1/admin/accounts/" + target + "/history")
                    .header("Authorization", "Bearer " + admin)
                    .exchange()
                    .expectStatus()
                    .isNotFound();
        }
    }

    @Test
    void longestUsernamesRemainPageableWithBoundedCursors() {
        String admin = token("personnel-admin"), prefix = "a".repeat(100);
        for (String suffix : new String[] {"01", "02"}) {
            post(
                    admin,
                    "",
                    null,
                    Map.of(
                            "username",
                            prefix + "b".repeat(18) + suffix,
                            "display_name",
                            "长账号验收",
                            "role",
                            "REVIEWER",
                            "password",
                            "synthetic-pass",
                            "reason",
                            "最大长度游标验收"),
                    201);
        }
        JsonNode first = read(admin, "?limit=1&query=" + prefix);
        String cursor = first.at("/page/next_cursor").stringValue();
        assertThat(cursor.length()).isGreaterThan(200).isLessThanOrEqualTo(256);
        assertThat(read(admin, "?limit=1&query=" + prefix + "&cursor=" + cursor)
                        .get("items")
                        .size())
                .isEqualTo(1);
        rest.get()
                .uri("/api/v1/admin/accounts?cursor=" + "a".repeat(257))
                .header("Authorization", "Bearer " + admin)
                .exchange()
                .expectStatus()
                .isBadRequest();
    }

    @Test
    void newStaffCanLoginClaimAndHasAnAuditWithoutPlaintextPasswords() {
        String admin = token("personnel-admin");
        JsonNode created = post(
                admin,
                "",
                null,
                Map.of(
                        "username",
                        "personnel-new",
                        "display_name",
                        "新售后专员",
                        "role",
                        "REVIEWER",
                        "password",
                        "initial-pass-1",
                        "reason",
                        "新增合成人员"),
                201);
        assertThat(created.at("/account/version").longValue()).isEqualTo(1);
        String worker = login("personnel-new", "initial-pass-1");
        String id = UUID.randomUUID().toString();
        jdbc.update(
                "INSERT INTO aftersale_case (case_id,merchant_id,customer_id,order_id,line_id,description,status,input_revision,version,created_at,updated_at) VALUES (?,'M-personnel','C-personnel',?,'personnel-line','合成申请','PENDING_REVIEW',1,1,NOW(6),NOW(6))",
                id,
                UUID.randomUUID().toString());
        rest.post()
                .uri("/api/v1/cases/" + id + "/collaboration")
                .header("Authorization", "Bearer " + worker)
                .header("If-Collaboration-Match", "\"0\"")
                .contentType(MediaType.APPLICATION_JSON)
                .body(Map.of("action", "CLAIM", "reason", "领取新合成工单"))
                .exchange()
                .expectStatus()
                .isOk();
        assertThat(jdbc.queryForObject("SELECT version FROM aftersale_case WHERE case_id=?", Long.class, id))
                .isEqualTo(1);
        post(admin, "/personnel-new", "\"1\"", update("REVIEWER", false, "新售后专员"), 200);
        assertThat(jdbc.queryForObject(
                        "SELECT owner_username FROM case_collaboration WHERE case_id=?", String.class, id))
                .isEqualTo("personnel-new");
        assertThat(jdbc.queryForObject("SELECT input_revision FROM aftersale_case WHERE case_id=?", Long.class, id))
                .isEqualTo(1);
        String audit = read(admin, "/personnel-new/history").toString();
        assertThat(audit)
                .contains("CREATED", "personnel-admin", "新增合成人员")
                .doesNotContain("initial-pass", "password_hash", "pbkdf2");
        post(
                admin,
                "",
                null,
                Map.of(
                        "username",
                        "personnel-new",
                        "display_name",
                        "同名",
                        "role",
                        "REVIEWER",
                        "password",
                        "initial-pass-2",
                        "reason",
                        "重复"),
                409);
    }

    @Test
    void disableReenableRoleChangeAndPasswordResetInvalidateOldSessions() {
        String admin = token("personnel-admin"), old = token("personnel-worker");
        post(admin, "/personnel-worker", "\"1\"", update("REVIEWER", false, "专员"), 200);
        rest.get()
                .uri("/api/v1/auth/me")
                .header("Authorization", "Bearer " + old)
                .exchange()
                .expectStatus()
                .isUnauthorized();
        post(admin, "/personnel-worker", "\"2\"", update("REVIEWER", true, "专员"), 200);
        rest.get()
                .uri("/api/v1/auth/me")
                .header("Authorization", "Bearer " + old)
                .exchange()
                .expectStatus()
                .isUnauthorized();
        String current = token("personnel-worker");
        post(admin, "/personnel-worker", "\"3\"", update("MERCHANT_ADMIN", true, "专员"), 200);
        rest.get()
                .uri("/api/v1/auth/me")
                .header("Authorization", "Bearer " + current)
                .exchange()
                .expectStatus()
                .isUnauthorized();
        String promoted = token("personnel-worker");
        post(admin, "/personnel-worker/password", "\"4\"", Map.of("password", "reset-pass-1", "reason", "重置合成人员"), 200);
        rest.get()
                .uri("/api/v1/auth/me")
                .header("Authorization", "Bearer " + promoted)
                .exchange()
                .expectStatus()
                .isUnauthorized();
        rest.post()
                .uri("/api/v1/auth/login")
                .contentType(MediaType.APPLICATION_JSON)
                .body(Map.of("username", "personnel-worker", "password", "demo-pass-1003"))
                .exchange()
                .expectStatus()
                .isUnauthorized();
        assertThat(login("personnel-worker", "reset-pass-1")).isNotBlank();
    }

    @Test
    void displayNameHasSeparateVersionAndStaleWritesCannotOverwriteOrReset() {
        String admin = token("personnel-admin"), worker = token("personnel-worker");
        post(admin, "/personnel-worker", "\"1\"", update("REVIEWER", true, "维护后姓名"), 200);
        rest.get()
                .uri("/api/v1/auth/me")
                .header("Authorization", "Bearer " + worker)
                .exchange()
                .expectStatus()
                .isOk();
        post(admin, "/personnel-worker", "\"1\"", update("REVIEWER", false, "过期覆盖"), 409);
        post(admin, "/personnel-worker/password", "\"1\"", Map.of("password", "stale-pass-1", "reason", "过期重置"), 409);
        post(admin, "/personnel-worker", null, update("REVIEWER", false, "无版本"), 409);
        post(admin, "/personnel-worker", "2", update("REVIEWER", false, "坏版本"), 422);
        assertThat(jdbc.queryForObject(
                        "SELECT display_name FROM identity_account WHERE username='personnel-worker'", String.class))
                .isEqualTo("维护后姓名");
        assertThat(read(admin, "/personnel-worker/history").get("items").size()).isEqualTo(1);
    }

    @Test
    void lastEnabledAdministratorCannotBeDisabledOrDemotedAndSelfChangeIsExplicitlyInvalidated() {
        String only = token("personnel-other-admin");
        post(only, "/personnel-other-admin", "\"1\"", update("MERCHANT_ADMIN", false, "仅管理员"), 409);
        post(only, "/personnel-other-admin", "\"1\"", update("REVIEWER", true, "仅管理员"), 409);
        assertThat(read(only, "/personnel-other-admin/history").get("items").size())
                .isZero();
        String admin = token("personnel-admin");
        JsonNode result = post(admin, "/personnel-admin", "\"1\"", update("REVIEWER", true, "降级自己"), 200);
        assertThat(result.get("session_invalidated").booleanValue()).isTrue();
        rest.get()
                .uri("/api/v1/admin/accounts")
                .header("Authorization", "Bearer " + admin)
                .exchange()
                .expectStatus()
                .isUnauthorized();
    }

    @Test
    void fixedBindingsAndMinimumPasswordPolicyAreEnforced() {
        String admin = token("personnel-admin");
        post(admin, "/personnel-customer", "\"1\"", update("REVIEWER", true, "非法角色转换"), 422);
        for (String role : new String[] {"CUSTOMER", "OPERATOR", "UNKNOWN"})
            post(
                    admin,
                    "",
                    null,
                    Map.of(
                            "username",
                            "personnel-new",
                            "display_name",
                            "新增",
                            "role",
                            role,
                            "password",
                            "initial-pass-1",
                            "reason",
                            "新增"),
                    422);
        post(
                admin,
                "",
                null,
                Map.of(
                        "username",
                        "personnel-new",
                        "display_name",
                        "新增",
                        "role",
                        "REVIEWER",
                        "password",
                        "short",
                        "reason",
                        "新增"),
                422);
        post(
                admin,
                "",
                null,
                Map.of(
                        "username",
                        "personnel-new",
                        "display_name",
                        "新增",
                        "role",
                        "REVIEWER",
                        "password",
                        "initial-pass-1",
                        "reason",
                        "新增",
                        "merchant_id",
                        "M-personnel-other"),
                400);
    }

    private RequestPrincipalResolver.Session session(String name) {
        return principals.session("Bearer " + token(name));
    }

    private StaffAdminService.Update disable() {
        return new StaffAdminService.Update("管理员", "MERCHANT_ADMIN", false, "合成并发维护");
    }

    @Test
    void concurrentAdministratorsCannotDisableTheLastAdministrator() throws Exception {
        var first = session("personnel-admin");
        var second = session("personnel-admin2");
        try (var executor = Executors.newVirtualThreadPerTaskExecutor()) {
            CountDownLatch start = new CountDownLatch(1);
            var a = executor.submit(() -> {
                start.await();
                return disableResult(first);
            });
            var b = executor.submit(() -> {
                start.await();
                return disableResult(second);
            });
            start.countDown();
            assertThat(java.util.List.of(a.get(10, TimeUnit.SECONDS), b.get(10, TimeUnit.SECONDS)))
                    .containsExactlyInAnyOrder("OK", "CONFLICT");
        }
        assertThat(jdbc.queryForObject(
                        "SELECT COUNT(*) FROM identity_account WHERE merchant_id='M-personnel' AND role='MERCHANT_ADMIN' AND enabled=TRUE",
                        Long.class))
                .isEqualTo(1);
        assertThat(jdbc.queryForObject(
                        "SELECT COUNT(*) FROM identity_account_audit WHERE merchant_id='M-personnel'", Long.class))
                .isEqualTo(1);
    }

    private String disableResult(RequestPrincipalResolver.Session session) {
        try {
            staff.update(session, session.principal().subject(), "\"1\"", disable());
            return "OK";
        } catch (com.resolveflow.caseservice.casefile.CaseStateConflictException error) {
            return "CONFLICT";
        }
    }

    @Test
    void identityRevokedWhileWaitingForMerchantLockCannotWrite() throws Exception {
        var actor = session("personnel-admin");
        try (var executor = Executors.newVirtualThreadPerTaskExecutor()) {
            var pending = new java.util.concurrent.atomic.AtomicReference<java.util.concurrent.Future<?>>();
            new TransactionTemplate(transactions).executeWithoutResult(status -> {
                jdbc.queryForObject(
                        "SELECT enabled FROM identity_merchant WHERE merchant_id='M-personnel' FOR UPDATE",
                        Boolean.class);
                CountDownLatch entered = new CountDownLatch(1);
                pending.set(executor.submit(() -> {
                    entered.countDown();
                    return staff.update(
                            actor,
                            "personnel-worker",
                            "\"1\"",
                            new StaffAdminService.Update("不应保存", "REVIEWER", true, "失效签名"));
                }));
                try {
                    assertThat(entered.await(5, TimeUnit.SECONDS)).isTrue();
                } catch (InterruptedException error) {
                    throw new RuntimeException(error);
                }
                assertThatThrownBy(() -> pending.get().get(200, TimeUnit.MILLISECONDS))
                        .isInstanceOf(TimeoutException.class);
                jdbc.update(
                        "UPDATE identity_account SET identity_version=identity_version+1 WHERE username='personnel-admin'");
            });
            assertThatThrownBy(() -> pending.get().get(10, TimeUnit.SECONDS))
                    .hasCauseInstanceOf(RequestPrincipalResolver.UnauthenticatedException.class);
        }
        assertThat(jdbc.queryForObject(
                        "SELECT account_version FROM identity_account WHERE username='personnel-worker'", Long.class))
                .isEqualTo(1);
        assertThat(jdbc.queryForObject(
                        "SELECT COUNT(*) FROM identity_account_audit WHERE merchant_id='M-personnel'", Long.class))
                .isZero();
    }

    @Test
    void currentLockingReadRejectsVersionChangedAfterVisibilitySnapshot() throws Exception {
        var actor = session("personnel-admin");
        try (var executor = Executors.newVirtualThreadPerTaskExecutor()) {
            var pending = new java.util.concurrent.atomic.AtomicReference<java.util.concurrent.Future<?>>();
            new TransactionTemplate(transactions).executeWithoutResult(status -> {
                jdbc.queryForObject(
                        "SELECT enabled FROM identity_account WHERE username='personnel-admin' FOR UPDATE",
                        Boolean.class);
                CountDownLatch entered = new CountDownLatch(1);
                pending.set(executor.submit(() -> {
                    entered.countDown();
                    return staff.update(
                            actor,
                            "personnel-worker",
                            "\"1\"",
                            new StaffAdminService.Update("过期覆盖", "REVIEWER", true, "并发维护"));
                }));
                try {
                    assertThat(entered.await(5, TimeUnit.SECONDS)).isTrue();
                } catch (InterruptedException error) {
                    throw new RuntimeException(error);
                }
                assertThatThrownBy(() -> pending.get().get(200, TimeUnit.MILLISECONDS))
                        .isInstanceOf(TimeoutException.class);
                jdbc.update(
                        "UPDATE identity_account SET account_version=account_version+1,display_name='先到修改' WHERE username='personnel-worker'");
            });
            assertThatThrownBy(() -> pending.get().get(10, TimeUnit.SECONDS))
                    .hasCauseInstanceOf(com.resolveflow.caseservice.casefile.CaseStateConflictException.class);
        }
        assertThat(jdbc.queryForObject(
                        "SELECT display_name FROM identity_account WHERE username='personnel-worker'", String.class))
                .isEqualTo("先到修改");
        assertThat(jdbc.queryForObject(
                        "SELECT COUNT(*) FROM identity_account_audit WHERE merchant_id='M-personnel'", Long.class))
                .isZero();
    }
}
