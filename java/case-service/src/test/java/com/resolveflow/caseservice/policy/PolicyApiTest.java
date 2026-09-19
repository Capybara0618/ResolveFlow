package com.resolveflow.caseservice.policy;

import static org.assertj.core.api.Assertions.assertThat;

import com.resolveflow.caseservice.CaseDatabaseTest;
import com.resolveflow.shared.security.AuthenticatedPrincipal;
import com.resolveflow.shared.security.JwtCodec;
import com.resolveflow.shared.security.Role;
import java.io.IOException;
import java.nio.file.Path;
import java.time.Duration;
import java.time.Instant;
import java.util.List;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.io.TempDir;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.boot.resttestclient.autoconfigure.AutoConfigureRestTestClient;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.test.web.servlet.client.RestTestClient;
import tools.jackson.databind.JsonNode;
import tools.jackson.databind.ObjectMapper;

/**
 * {@code GET /internal/v1/policies/{bundle_id}} over HTTP.
 *
 * <p>The route exists so Java can re-check a citation against the policy text rather than against the Agent's
 * summary (docs/core-contracts.md:51). The test therefore compares the served text with what was imported,
 * member by member and rule by rule, and pins the two boundaries that make the route safe to exist at all:
 * the internal surface is service-only, and an unknown bundle is a 404 in the shared error shape.
 */
@SpringBootTest(webEnvironment = SpringBootTest.WebEnvironment.RANDOM_PORT)
@AutoConfigureRestTestClient
class PolicyApiTest extends CaseDatabaseTest {

    private static final ObjectMapper MAPPER = new ObjectMapper();

    @Autowired
    RestTestClient rest;

    @Autowired
    PolicyImportService imports;

    @Value("${resolveflow.identity.jwt.secret}")
    String secret;

    @TempDir
    Path temp;

    private static final String BUNDLE = """
            bundle_id: policy-logistics-2026.09
            version: "2026.09"
            safety_epoch: 2
            effective_from: "2026-09-01T00:00:00Z"
            effective_to: null
            rules:
              - rule_id: R-LOST-001
                title: 承运商判定丢失
                text: 承运商结论为 LOST 且无有效签收记录时，可按该订单行支付金额全额退款。
              - rule_id: R-NOSCAN-7D
                title: 七天无扫描
                text: 承运商无有效签收且连续 7 天无扫描记录时，视同丢失。
            """;

    @BeforeEach
    void importTheBundle() throws IOException {
        jdbc.execute("DELETE FROM policy_rule");
        jdbc.execute("DELETE FROM policy_bundle");
        java.nio.file.Files.writeString(temp.resolve("b.yaml"), BUNDLE, java.nio.charset.StandardCharsets.UTF_8);
        imports.importDirectory(temp);
    }

    private String serviceToken() {
        return new JwtCodec(secret, Duration.ofHours(1)).issueServiceToken("agent-service", Instant.now());
    }

    private String userToken() {
        return new JwtCodec(secret, Duration.ofHours(1))
                .issue(new AuthenticatedPrincipal("demo-customer", "M-1001", Role.CUSTOMER, "C-2002"), Instant.now());
    }

    @Test
    @DisplayName("the served rules are the imported text, in source order, with the stored hash")
    void servesTheAuthoritativeText() {
        String body = rest.get()
                .uri("/internal/v1/policies/policy-logistics-2026.09")
                .header("Authorization", "Bearer " + serviceToken())
                .exchange()
                .expectStatus()
                .isOk()
                .expectBody(String.class)
                .returnResult()
                .getResponseBody();

        JsonNode json = MAPPER.readTree(body);
        assertThat(json.properties().stream().map(java.util.Map.Entry::getKey))
                .as("exactly the contract's members; the effective window is internal, not part of the response")
                .containsExactlyInAnyOrder("bundle_id", "version", "manifest_hash", "safety_epoch", "rules");
        assertThat(json.get("bundle_id").stringValue()).isEqualTo("policy-logistics-2026.09");
        assertThat(json.get("version").stringValue()).isEqualTo("2026.09");
        assertThat(json.get("safety_epoch").asInt()).isEqualTo(2);
        assertThat(json.get("manifest_hash").stringValue()).matches("[a-f0-9]{64}");
        assertThat(json.get("manifest_hash").stringValue())
                .as("the hash of the stored version, so a citation can be pinned to it")
                .isEqualTo(jdbc.queryForObject(
                        "SELECT manifest_hash FROM policy_bundle WHERE bundle_id = ?",
                        String.class,
                        "policy-logistics-2026.09"));

        assertThat(json.get("rules")).hasSize(2);
        JsonNode first = json.get("rules").get(0);
        assertThat(first.properties().stream().map(java.util.Map.Entry::getKey))
                .containsExactlyInAnyOrder("rule_id", "title", "text");
        assertThat(first.get("rule_id").stringValue()).isEqualTo("R-LOST-001");
        assertThat(first.get("text").stringValue())
                .as("byte for byte what the policy author wrote, which is the whole point of the route")
                .isEqualTo("承运商结论为 LOST 且无有效签收记录时，可按该订单行支付金额全额退款。");
        assertThat(json.get("rules").get(1).get("rule_id").stringValue())
                .as("source order, not whatever order the table returned")
                .isEqualTo("R-NOSCAN-7D");
    }

    @Test
    @DisplayName("no token is 401 and a user token is 403: this surface is for the Agent, not for people")
    void theInternalSurfaceIsServiceOnly() {
        rest.get()
                .uri("/internal/v1/policies/policy-logistics-2026.09")
                .exchange()
                .expectStatus()
                .isUnauthorized()
                .expectBody(String.class)
                .value(response -> assertThat(
                                MAPPER.readTree(response).get("code").stringValue())
                        .isEqualTo("UNAUTHENTICATED"));

        rest.get()
                .uri("/internal/v1/policies/policy-logistics-2026.09")
                .header("Authorization", "Bearer " + userToken())
                .exchange()
                .expectStatus()
                .isForbidden()
                .expectBody(String.class)
                .value(response -> assertThat(
                                MAPPER.readTree(response).get("code").stringValue())
                        .isEqualTo("FORBIDDEN_SCOPE"));
    }

    @Test
    @DisplayName("an unknown bundle is 404 in the shared error shape, not an empty rule list")
    void unknownBundleIsNotFound() {
        rest.get()
                .uri("/internal/v1/policies/policy-logistics-2039.01")
                .header("Authorization", "Bearer " + serviceToken())
                .exchange()
                .expectStatus()
                .isNotFound()
                .expectBody(String.class)
                .value(response -> {
                    JsonNode json = MAPPER.readTree(response);
                    assertThat(json.get("code").stringValue()).isEqualTo("NOT_FOUND");
                    assertThat(json.get("trace_id").isNull()).isFalse();
                });
    }

    @Test
    @DisplayName("a bundle with no rules is impossible to store, so the route always serves a checkable rule set")
    void everyStoredBundleHasRules() {
        List<String> bundles =
                jdbc.queryForList("SELECT bundle_id FROM policy_bundle ORDER BY bundle_id", String.class);
        assertThat(bundles).containsExactly("policy-logistics-2026.09");
        assertThat(jdbc.queryForObject(
                        "SELECT COUNT(*) FROM policy_rule WHERE bundle_id = ?",
                        Integer.class,
                        "policy-logistics-2026.09"))
                .isEqualTo(2);
    }
}
