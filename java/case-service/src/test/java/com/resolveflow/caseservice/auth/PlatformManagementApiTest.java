package com.resolveflow.caseservice.auth;

import static org.assertj.core.api.Assertions.*;

import com.resolveflow.caseservice.CaseDatabaseTest;
import com.resolveflow.caseservice.shopping.CommerceShoppingClient;
import com.resolveflow.shared.security.DemoAccounts;
import com.resolveflow.shared.security.JwtCodec;
import com.resolveflow.shared.shopping.ManagementWire.StoreSync;
import java.util.Map;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.resttestclient.autoconfigure.AutoConfigureRestTestClient;
import org.springframework.boot.test.context.TestConfiguration;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Primary;
import org.springframework.test.web.servlet.client.RestTestClient;
import org.springframework.web.client.RestClient;
import tools.jackson.databind.JsonNode;

@AutoConfigureRestTestClient
class PlatformManagementApiTest extends CaseDatabaseTest {
    @Autowired
    RestTestClient rest;

    @Autowired
    StubCommerce commerce;

    @TestConfiguration
    static class Configuration {
        @Bean
        @Primary
        StubCommerce stub(RestClient.Builder builder, JwtCodec codec) {
            return new StubCommerce(builder, codec);
        }
    }

    static class StubCommerce extends CommerceShoppingClient {
        boolean fail;

        StubCommerce(RestClient.Builder b, JwtCodec c) {
            super(b, c, "http://127.0.0.1:9");
        }

        @Override
        public StoreSync syncStore(StoreSync r) {
            if (fail) throw new Refused(409, "TEST_UNAVAILABLE", "合成同步中断");
            return r;
        }
    }

    @BeforeEach
    void setup() {
        commerce.fail = false;
        jdbc.update(
                "DELETE FROM buyer_customer_binding WHERE merchant_id='FOUNDATION-TEST' OR buyer_id IN (SELECT buyer_id FROM identity_account WHERE username='foundation-buyer')");
        jdbc.update(
                "DELETE FROM identity_account WHERE username IN ('foundation-platform','foundation-admin','foundation-buyer')");
        jdbc.update("DELETE FROM identity_merchant WHERE merchant_id='FOUNDATION-TEST'");
        jdbc.update(
                "INSERT INTO identity_account(username,role,display_name,password_hash) VALUES ('foundation-platform','PLATFORM_ADMIN','平台测试',?)",
                DemoAccounts.hashPassword("123456", "test-salt-foundation".getBytes(), 120000));
    }

    @AfterEach
    void cleanup() {
        var ids = jdbc.queryForList(
                "SELECT buyer_id FROM identity_account WHERE username='foundation-buyer'", String.class);
        jdbc.update(
                "DELETE FROM buyer_customer_binding WHERE merchant_id='FOUNDATION-TEST' OR buyer_id IN (SELECT buyer_id FROM identity_account WHERE username='foundation-buyer')");
        jdbc.update(
                "DELETE FROM identity_account WHERE username IN ('foundation-platform','foundation-admin','foundation-buyer')");
        jdbc.update("DELETE FROM identity_merchant WHERE merchant_id='FOUNDATION-TEST'");
        for (var id : ids) jdbc.update("DELETE FROM platform_buyer WHERE buyer_id=?", id);
    }

    private String login(String name, String password) {
        return rest.post()
                .uri("/api/v1/auth/login")
                .body(Map.of("username", name, "password", password))
                .exchange()
                .expectStatus()
                .isOk()
                .expectBody(JsonNode.class)
                .returnResult()
                .getResponseBody()
                .get("access_token")
                .asString();
    }

    private JsonNode create(String token, String path, Object body, int status) {
        return rest.post()
                .uri(path)
                .header("Authorization", "Bearer " + token)
                .body(body)
                .exchange()
                .expectStatus()
                .isEqualTo(status)
                .expectBody(JsonNode.class)
                .returnResult()
                .getResponseBody();
    }

    @Test
    void platformHasOnlyPlatformRoutesAndMerchantOrBuyerCannotProvision() {
        String token = login("foundation-platform", "123456");
        rest.get()
                .uri("/api/v1/auth/me")
                .header("Authorization", "Bearer " + token)
                .exchange()
                .expectStatus()
                .isOk()
                .expectBody()
                .jsonPath("$.role")
                .isEqualTo("PLATFORM_ADMIN")
                .jsonPath("$.merchant_id")
                .doesNotExist();
        for (var path : java.util.List.of(
                "/api/v1/review/cases", "/api/v1/orders", "/api/v1/merchant/products", "/api/v1/cases/unknown"))
            rest.get()
                    .uri(path)
                    .header("Authorization", "Bearer " + token)
                    .exchange()
                    .expectStatus()
                    .isForbidden();
        for (var credentials : new String[][] {
            {"demo-admin", "demo-pass-1100"}, {"demo-reviewer", "demo-pass-1003"}, {"demo-buyer", "demo-pass-4001"}
        })
            rest.get()
                    .uri("/api/v1/platform/buyers")
                    .header("Authorization", "Bearer " + login(credentials[0], credentials[1]))
                    .exchange()
                    .expectStatus()
                    .isForbidden();
    }

    @Test
    void newBuyerBindsAllStoresAndDisableInvalidatesExistingSession() {
        String token = login("foundation-platform", "123456");
        var created = create(
                token,
                "/api/v1/platform/buyers",
                Map.of("username", "foundation-buyer", "display_name", "新买家", "password", "123456", "reason", "合成测试"),
                201);
        assertThat(created.toString()).doesNotContain("password", "pbkdf2", "buyer_id");
        assertThat(jdbc.queryForObject(
                        "SELECT COUNT(*) FROM buyer_customer_binding WHERE buyer_id=(SELECT buyer_id FROM identity_account WHERE username='foundation-buyer')",
                        Long.class))
                .isEqualTo(jdbc.queryForObject("SELECT COUNT(*) FROM identity_merchant", Long.class));
        String buyer = login("foundation-buyer", "123456");
        create(
                token,
                "/api/v1/platform/buyers/foundation-buyer",
                Map.of("display_name", "新买家", "enabled", false, "expected_version", 1, "reason", "停用测试"),
                200);
        rest.get()
                .uri("/api/v1/auth/me")
                .header("Authorization", "Bearer " + buyer)
                .exchange()
                .expectStatus()
                .isUnauthorized();
        create(
                token,
                "/api/v1/platform/buyers/foundation-buyer",
                Map.of("display_name", "新买家", "enabled", true, "expected_version", 1, "reason", "过期编辑"),
                409);
    }

    @Test
    void interruptedMerchantProvisionRemainsDisabledAndSameRequestResumesWithoutDuplicates() {
        String token = login("foundation-platform", "123456");
        var body = Map.of(
                "merchant_id",
                "FOUNDATION-TEST",
                "name",
                "合成商家",
                "description",
                "合成商家说明",
                "username",
                "foundation-admin",
                "display_name",
                "新管理员",
                "password",
                "123456",
                "reason",
                "合成测试");
        commerce.fail = true;
        create(token, "/api/v1/platform/merchants", body, 409);
        assertThat(jdbc.queryForObject(
                        "SELECT enabled FROM identity_merchant WHERE merchant_id='FOUNDATION-TEST'", Boolean.class))
                .isFalse();
        commerce.fail = false;
        create(token, "/api/v1/platform/merchants", body, 201);
        create(token, "/api/v1/platform/merchants", body, 201);
        assertThat(jdbc.queryForObject(
                        "SELECT COUNT(*) FROM identity_account WHERE username='foundation-admin'", Long.class))
                .isEqualTo(1);
        assertThat(jdbc.queryForObject(
                        "SELECT enabled FROM identity_merchant WHERE merchant_id='FOUNDATION-TEST'", Boolean.class))
                .isTrue();
        login("foundation-admin", "123456");
    }
}
