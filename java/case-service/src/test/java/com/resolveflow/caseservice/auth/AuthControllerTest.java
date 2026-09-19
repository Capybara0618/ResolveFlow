package com.resolveflow.caseservice.auth;

import static org.assertj.core.api.Assertions.assertThat;

import com.resolveflow.shared.security.JwtCodec;
import com.resolveflow.shared.security.Role;
import java.time.Instant;
import java.util.Map;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.resttestclient.autoconfigure.AutoConfigureRestTestClient;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.http.MediaType;
import org.springframework.test.web.servlet.client.RestTestClient;
import tools.jackson.databind.JsonNode;
import tools.jackson.databind.ObjectMapper;

/**
 * The demonstration login endpoint: POST /api/v1/auth/login (docs/core-contracts.md, route table).
 *
 * <p>It needs no token (it is how a token is obtained) and answers with the core OpenAPI's
 * LoginResponse shape exactly — snake_case, token_type Bearer, role and merchant_id. Failures use the
 * shared error body so the gateway and the Agent see one error shape everywhere.
 */
@SpringBootTest(webEnvironment = SpringBootTest.WebEnvironment.RANDOM_PORT)
@AutoConfigureRestTestClient
class AuthControllerTest {

    private static final ObjectMapper MAPPER = new ObjectMapper();

    @Autowired
    RestTestClient rest;

    @Autowired
    JwtCodec jwtCodec;

    @Test
    @DisplayName("a seeded account exchanges for a token, with no Authorization header")
    void loginIssuesAToken() {
        String body = rest.post()
                .uri("/api/v1/auth/login")
                .contentType(MediaType.APPLICATION_JSON)
                .body(Map.of("username", "demo-customer", "password", "demo-pass-1001"))
                .exchange()
                .expectStatus()
                .isOk()
                .expectBody(String.class)
                .returnResult()
                .getResponseBody();

        JsonNode json = MAPPER.readTree(body);
        assertThat(json.get("token_type").stringValue()).isEqualTo("Bearer");
        assertThat(json.get("role").stringValue()).isEqualTo("CUSTOMER");
        assertThat(json.get("merchant_id").stringValue()).isEqualTo("M-1001");
        assertThat(json.get("customer_id").stringValue()).isEqualTo("C-2002");
        assertThat(json.get("expires_in").asInt()).isBetween(1, 86400);
        assertThat(json.get("access_token").stringValue()).isNotBlank();
        assertThat(json.properties().stream().map(Map.Entry::getKey))
                .as("no extra members: the schema is additionalProperties: false")
                .containsExactlyInAnyOrder(
                        "access_token", "token_type", "expires_in", "role", "merchant_id", "customer_id");
    }

    @Test
    @DisplayName("an identity header changes nothing, even when the gateway is bypassed")
    void identityHeadersAreNeverTrusted() {
        // The gateway strips these (IdentityHeaderStripFilter), but the service must not depend on that:
        // a direct in-cluster call must be just as unable to name its own principal
        // (docs/core-contracts.md:15). The merchant below is the *other* merchant on purpose.
        String body = rest.post()
                .uri("/api/v1/auth/login")
                .contentType(MediaType.APPLICATION_JSON)
                .header("X-User", "demo-customer-m2")
                .header("X-Role", "OPERATOR")
                .header("X-Merchant", "M-1002")
                .header("X-Customer", "C-2004")
                .body(Map.of("username", "demo-customer", "password", "demo-pass-1001"))
                .exchange()
                .expectStatus()
                .isOk()
                .expectBody(String.class)
                .returnResult()
                .getResponseBody();

        JsonNode json = MAPPER.readTree(body);
        assertThat(json.get("merchant_id").stringValue()).isEqualTo("M-1001");
        assertThat(json.get("customer_id").stringValue()).isEqualTo("C-2002");
        assertThat(json.get("role").stringValue()).isEqualTo("CUSTOMER");
    }

    @Test
    @DisplayName("the issued token is one this service would accept as its principal")
    void issuedTokenVerifiesAsAUserToken() {
        String body = rest.post()
                .uri("/api/v1/auth/login")
                .contentType(MediaType.APPLICATION_JSON)
                .body(Map.of("username", "demo-reviewer", "password", "demo-pass-1003"))
                .exchange()
                .expectStatus()
                .isOk()
                .expectBody(String.class)
                .returnResult()
                .getResponseBody();

        String token = MAPPER.readTree(body).get("access_token").stringValue();
        // Verified with the codec this service actually wired, not with a copy of the secret: a test
        // that re-declares the key would keep passing after the service was wired to another one.
        assertThat(jwtCodec.principalFromAuthorizationHeader("Bearer " + token, Instant.now())
                        .role())
                .isEqualTo(Role.REVIEWER);
    }

    @Test
    @DisplayName("a bad password is a 401 in the shared error shape, not a 500 or a stack trace")
    void badPasswordIsOneErrorShape() {
        rest.post()
                .uri("/api/v1/auth/login")
                .contentType(MediaType.APPLICATION_JSON)
                .body(Map.of("username", "demo-customer", "password", "nope"))
                .exchange()
                .expectStatus()
                .isUnauthorized()
                .expectBody(String.class)
                .value(body -> {
                    JsonNode json = MAPPER.readTree(body);
                    assertThat(json.get("code").stringValue()).isEqualTo("UNAUTHENTICATED");
                    assertThat(json.get("retryable").asBoolean()).isFalse();
                    assertThat(json.get("message").stringValue()).isEqualTo("invalid username or password");
                    assertThat(json.get("trace_id").isNull()).isFalse();
                });
    }

    @Test
    @DisplayName("an unknown account is refused the same way a wrong password is")
    void unknownAccountIsRefusedTheSameWay() {
        rest.post()
                .uri("/api/v1/auth/login")
                .contentType(MediaType.APPLICATION_JSON)
                .body(Map.of("username", "no-such-user", "password", "demo-pass-1001"))
                .exchange()
                .expectStatus()
                .isUnauthorized()
                .expectBody(String.class)
                .value(body -> assertThat(MAPPER.readTree(body).get("message").stringValue())
                        .isEqualTo("invalid username or password"));
    }

    @Test
    @DisplayName("a caller cannot ask for someone else's identity in the body")
    void identityCannotBeRequestedInTheBody() {
        rest.post()
                .uri("/api/v1/auth/login")
                .contentType(MediaType.APPLICATION_JSON)
                .body(Map.of(
                        "username", "demo-customer",
                        "password", "demo-pass-1001",
                        "merchant_id", "M-1002",
                        "role", "OPERATOR"))
                .exchange()
                .expectStatus()
                .isBadRequest()
                .expectBody(String.class)
                .value(body -> assertThat(MAPPER.readTree(body).get("code").stringValue())
                        .isEqualTo("INVALID_ARGUMENT"));
    }

    @Test
    @DisplayName("an unknown field is refused rather than ignored")
    void unknownFieldIsRefused() {
        rest.post()
                .uri("/api/v1/auth/login")
                .contentType(MediaType.APPLICATION_JSON)
                .body(Map.of("username", "demo-customer", "password", "demo-pass-1001", "nickname", "x"))
                .exchange()
                .expectStatus()
                .isBadRequest();
    }

    @Test
    @DisplayName("a blank username or password is refused as input, not as credentials")
    void blankInputIsRefused() {
        rest.post()
                .uri("/api/v1/auth/login")
                .contentType(MediaType.APPLICATION_JSON)
                .body(Map.of("username", "", "password", "demo-pass-1001"))
                .exchange()
                .expectStatus()
                .isBadRequest();
    }
}
