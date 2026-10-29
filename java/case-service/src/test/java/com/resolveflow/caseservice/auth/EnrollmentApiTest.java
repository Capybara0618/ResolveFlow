package com.resolveflow.caseservice.auth;

import com.resolveflow.caseservice.CaseDatabaseTest;
import java.util.*;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.resttestclient.autoconfigure.AutoConfigureRestTestClient;
import org.springframework.http.MediaType;
import org.springframework.test.web.servlet.client.RestTestClient;
import tools.jackson.databind.ObjectMapper;

@AutoConfigureRestTestClient
class EnrollmentApiTest extends CaseDatabaseTest {
    @Autowired
    RestTestClient rest;

    final ObjectMapper json = new ObjectMapper();

    @Test
    void registerAndRecoverAreUsableWithoutAuthenticationAndOnlyCreateBuyerAccounts() {
        String username = "http-signup-" + UUID.randomUUID().toString().substring(0, 8);
        String receipt = rest.post()
                .uri("/api/v1/auth/register")
                .contentType(MediaType.APPLICATION_JSON)
                .body(Map.of("username", username, "display_name", "测试买家", "password", "password-test"))
                .exchange()
                .expectStatus()
                .isCreated()
                .expectHeader()
                .valueEquals("Cache-Control", "no-store")
                .expectBody(String.class)
                .returnResult()
                .getResponseBody();
        String auth = rest.post()
                .uri("/api/v1/auth/login")
                .contentType(MediaType.APPLICATION_JSON)
                .body(Map.of("username", username, "password", "password-test"))
                .exchange()
                .expectStatus()
                .isOk()
                .expectBody(String.class)
                .returnResult()
                .getResponseBody();
        String token = json.readTree(auth).path("access_token").asString();
        rest.get()
                .uri("/api/v1/auth/me")
                .header("Authorization", "Bearer " + token)
                .exchange()
                .expectStatus()
                .isOk()
                .expectBody()
                .jsonPath("$.role")
                .isEqualTo("CUSTOMER")
                .jsonPath("$.merchant_id")
                .doesNotExist();
        rest.post()
                .uri("/api/v1/auth/recover")
                .contentType(MediaType.APPLICATION_JSON)
                .body(Map.of(
                        "username",
                        username,
                        "recovery_key",
                        json.readTree(receipt).path("recovery_key").asString(),
                        "new_password",
                        "new-password"))
                .exchange()
                .expectStatus()
                .isOk()
                .expectHeader()
                .valueEquals("Cache-Control", "no-store");
        rest.get()
                .uri("/api/v1/auth/me")
                .header("Authorization", "Bearer " + token)
                .exchange()
                .expectStatus()
                .isUnauthorized();
        rest.post()
                .uri("/api/v1/auth/register")
                .contentType(MediaType.APPLICATION_JSON)
                .body(Map.of(
                        "username",
                        username + "-evil",
                        "display_name",
                        "测试买家",
                        "password",
                        "password-test",
                        "role",
                        "PLATFORM_ADMIN"))
                .exchange()
                .expectStatus()
                .isBadRequest();
    }
}
