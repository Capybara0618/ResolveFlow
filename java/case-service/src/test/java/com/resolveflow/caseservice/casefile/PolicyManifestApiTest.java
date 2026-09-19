package com.resolveflow.caseservice.casefile;

import static org.assertj.core.api.Assertions.assertThat;

import com.resolveflow.caseservice.CaseDatabaseTest;
import com.resolveflow.caseservice.policy.PolicyManifestRepository;
import com.resolveflow.shared.security.AuthenticatedPrincipal;
import com.resolveflow.shared.security.JwtCodec;
import com.resolveflow.shared.security.Role;
import java.time.Duration;
import java.time.Instant;
import java.util.List;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.boot.resttestclient.autoconfigure.AutoConfigureRestTestClient;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.boot.test.context.TestConfiguration;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Primary;
import org.springframework.test.web.servlet.client.RestTestClient;
import tools.jackson.databind.JsonNode;
import tools.jackson.databind.ObjectMapper;

/**
 * Which policy a case is decided under, and the manifest it is pinned to (docs/core-contracts.md:50).
 *
 * <p>The property under test is a sentence from the contract: "a run is pinned to an immutable manifest; a
 * case never silently switches to a newer policy." Three tests make that concrete:
 *
 * <ul>
 *   <li>a payment in August is decided under the August bundle even though the request arrives in September,
 *   <li>importing a newer bundle afterwards changes nothing about an already-open case,
 *   <li>a payment no version covers is refused before anything is written, rather than decided under the
 *       nearest policy.
 * </ul>
 */
@SpringBootTest(webEnvironment = SpringBootTest.WebEnvironment.RANDOM_PORT)
@AutoConfigureRestTestClient
class PolicyManifestApiTest extends CaseDatabaseTest {

    private static final ObjectMapper MAPPER = new ObjectMapper();
    private static final Instant PAID_IN_AUGUST = Instant.parse("2026-08-20T10:00:00Z");
    private static final Instant PAID_IN_SEPTEMBER = Instant.parse("2026-09-10T08:15:00Z");

    /** The case tests' Commerce stub, but wired as the bean this test needs. */
    @TestConfiguration
    static class StubCommerceConfiguration {

        @Bean
        @Primary
        StubCommerce commerceStub(
                org.springframework.web.client.RestClient.Builder builder,
                @Value("${resolveflow.identity.jwt.secret}") String secret,
                @Value("${resolveflow.identity.jwt.service-token-ttl:PT1H}") Duration ttl) {
            return new StubCommerce(builder, new JwtCodec(secret, ttl));
        }
    }

    @Autowired
    RestTestClient rest;

    @Autowired
    StubCommerce commerce;

    @Autowired
    PolicyManifestRepository manifests;

    @Autowired
    CaseRepository cases;

    @Value("${resolveflow.identity.jwt.secret}")
    String secret;

    private long lineCounter = 7100;

    private String nextLine() {
        return String.valueOf(++lineCounter);
    }

    @BeforeEach
    void prepare() {
        // The two shipped versions, with their windows, are what selection is about; a test that left the
        // bundle set to something else would be testing a different question.
        jdbc.execute("DELETE FROM case_policy_bundle");
        jdbc.execute("DELETE FROM case_policy_manifest");
        jdbc.execute("DELETE FROM policy_rule");
        jdbc.execute("DELETE FROM policy_bundle");
        policies.importDirectory(fixtureDirectory());
        deleteAllCaseData(jdbc);
        commerce.lineVisible = true;
        commerce.paidAt = PAID_IN_SEPTEMBER;
    }

    private static java.nio.file.Path fixtureDirectory() {
        java.nio.file.Path candidate = java.nio.file.Path.of("").toAbsolutePath();
        for (int level = 0; level < 5 && candidate != null; level++) {
            java.nio.file.Path bundles =
                    candidate.resolve("fixtures").resolve("policies").resolve("bundles");
            if (java.nio.file.Files.isDirectory(bundles)) {
                return bundles;
            }
            candidate = candidate.getParent();
        }
        throw new IllegalStateException("fixtures/policies/bundles not found");
    }

    private String serviceToken() {
        return new JwtCodec(secret, Duration.ofHours(1)).issueServiceToken("agent-service", Instant.now());
    }

    private String userToken() {
        return new JwtCodec(secret, Duration.ofHours(1))
                .issue(new AuthenticatedPrincipal("demo-customer", "M-1001", Role.CUSTOMER, "C-2002"), Instant.now());
    }

    /** Opens a case and returns the response body, so a test can assert on what the caller was told. */
    private JsonNode openCase(String lineId, String key) {
        String body = rest.post()
                .uri("/api/v1/cases")
                .header("Authorization", "Bearer " + userToken())
                .header("Idempotency-Key", key)
                .contentType(org.springframework.http.MediaType.APPLICATION_JSON)
                .body("{\"line_id\":\"" + lineId + "\",\"description\":\"退款诉求\",\"requested_actions\":[\"REFUND\"]}")
                .exchange()
                .expectStatus()
                .isCreated()
                .expectBody(String.class)
                .returnResult()
                .getResponseBody();
        return MAPPER.readTree(body);
    }

    private JsonNode readManifest(String caseId) {
        String body = rest.get()
                .uri("/internal/v1/cases/" + caseId + "/policy-manifest")
                .header("Authorization", "Bearer " + serviceToken())
                .exchange()
                .expectStatus()
                .isOk()
                .expectBody(String.class)
                .returnResult()
                .getResponseBody();
        return MAPPER.readTree(body);
    }

    private String storedHash(String bundleId) {
        return jdbc.queryForObject(
                "SELECT manifest_hash FROM policy_bundle WHERE bundle_id = ?", String.class, bundleId);
    }

    @Test
    @DisplayName("a payment in August is decided under the August version, not the one current in September")
    void theVersionIsChosenByThePaymentTime() {
        commerce.paidAt = PAID_IN_AUGUST;
        JsonNode augustCase = openCase(nextLine(), "manifest-august");
        // The stub's payment time is a knob and stays where it was put, so it has to be moved back:
        // the first version of this test opened both cases with the August time and then wondered why
        // the September case had the August policy.
        commerce.paidAt = PAID_IN_SEPTEMBER;
        JsonNode septemberCase = openCase(nextLine(), "manifest-september");

        JsonNode august = readManifest(augustCase.get("case_id").stringValue());
        JsonNode september = readManifest(septemberCase.get("case_id").stringValue());

        assertThat(august.get("bundles").get(0).get("bundle_ids").get(0).stringValue())
                .as("the version in force when the order was paid for")
                .isEqualTo("policy-logistics-2026.08");
        assertThat(august.get("bundles").get(0).get("manifest_hash").stringValue())
                .isEqualTo(storedHash("policy-logistics-2026.08"));
        assertThat(august.get("bundles").get(0).get("safety_epoch").asInt()).isEqualTo(1);
        assertThat(august.get("effective_from").stringValue()).isEqualTo("2026-08-01T00:00:00Z");
        assertThat(august.get("effective_to").stringValue())
                .as("the August version was closed by the September one, and the case says so")
                .isEqualTo("2026-09-01T00:00:00Z");

        assertThat(september.get("bundles").get(0).get("bundle_ids").get(0).stringValue())
                .isEqualTo("policy-logistics-2026.09");
        assertThat(september.get("bundles").get(0).get("manifest_hash").stringValue())
                .isEqualTo(storedHash("policy-logistics-2026.09"));
        // Absent rather than null: the version is still in force, and "no end" is the absence of an end.
        assertThat(september.has("effective_to")).isFalse();
    }

    @Test
    @DisplayName("importing a newer policy afterwards changes nothing about an open case")
    void anOpenCaseNeverSwitchesToANewerPolicy() {
        JsonNode opened = openCase(nextLine(), "manifest-pinned");
        String caseId = opened.get("case_id").stringValue();
        String before = readManifest(caseId).toString();

        // A newer version, published after the case was opened. Its window starts after the payment time,
        // so it must not touch this case — and the previous version's window stays open, which is legal:
        // selection only ever looks at the payment time, so overlapping *open* windows are fine. The import
        // refuses overlaps, so this newer one starts after September and the case is unaffected.
        java.nio.file.Path extra = null;
        try {
            extra = java.nio.file.Files.createTempDirectory("policy-newer");
            java.nio.file.Files.writeString(extra.resolve("newer.yaml"), """
                    bundle_id: policy-logistics-2026.10
                    version: "2026.10"
                    safety_epoch: 3
                    effective_from: "2026-10-01T00:00:00Z"
                    effective_to: null
                    rules:
                      - rule_id: R-LOST-001
                        title: 承运商判定丢失
                        text: 新版把全额退款改成需人工核验后全额退款。
                    """, java.nio.charset.StandardCharsets.UTF_8);
            policies.importDirectory(extra);
        } catch (java.io.IOException error) {
            throw new IllegalStateException(error);
        } finally {
            if (extra != null) {
                try {
                    java.nio.file.Files.deleteIfExists(extra.resolve("newer.yaml"));
                    java.nio.file.Files.deleteIfExists(extra);
                } catch (java.io.IOException ignored) {
                    // a leftover temp directory is not worth failing a test over
                }
            }
        }

        assertThat(jdbc.queryForObject("SELECT COUNT(*) FROM policy_bundle", Integer.class))
                .as("the newer version really is installed")
                .isEqualTo(3);
        assertThat(readManifest(caseId).toString())
                .as("the case is decided under the policy it was opened under, forever")
                .isEqualTo(before);
    }

    @Test
    @DisplayName("a payment no version covers is refused before anything is written")
    void aPaymentOutsideEveryWindowIsRefused() {
        commerce.paidAt = Instant.parse("2026-07-01T00:00:00Z");

        rest.post()
                .uri("/api/v1/cases")
                .header("Authorization", "Bearer " + userToken())
                .header("Idempotency-Key", "manifest-gap")
                .contentType(org.springframework.http.MediaType.APPLICATION_JSON)
                .body("{\"line_id\":\"7199\",\"description\":\"退款诉求\",\"requested_actions\":[\"REFUND\"]}")
                .exchange()
                .expectStatus()
                // Spring Framework 7's StatusAssertions has no isUnprocessableContent():
                // the named helpers were trimmed to the common ones, and the suite
                // asserts this status numerically everywhere else too.
                .isEqualTo(422)
                .expectBody(String.class)
                .value(response -> {
                    JsonNode json = MAPPER.readTree(response);
                    assertThat(json.get("code").stringValue()).isEqualTo("SEMANTIC_INVALID");
                    assertThat(json.get("message").stringValue())
                            .as("the operator's next question is which version is missing, so the refusal lists "
                                    + "what is installed")
                            .contains("2026-07-01T00:00:00Z")
                            .contains("policy-logistics-2026.08")
                            .contains("policy-logistics-2026.09");
                });

        assertThat(jdbc.queryForObject("SELECT COUNT(*) FROM aftersale_case", Integer.class))
                .as("nothing was written: a case no policy can decide is never opened")
                .isZero();
        assertThat(jdbc.queryForObject("SELECT COUNT(*) FROM active_case_slot", Integer.class))
                .isZero();
    }

    @Test
    @DisplayName("the manifest route is service-only, and unknown cases and unpinned cases are both 404")
    void theManifestRouteRefusesWhatItCannotAnswer() {
        JsonNode opened = openCase(nextLine(), "manifest-scope");
        String caseId = opened.get("case_id").stringValue();

        rest.get()
                .uri("/internal/v1/cases/" + caseId + "/policy-manifest")
                .exchange()
                .expectStatus()
                .isUnauthorized()
                .expectBody(String.class)
                .value(response -> assertThat(
                                MAPPER.readTree(response).get("code").stringValue())
                        .isEqualTo("UNAUTHENTICATED"));

        rest.get()
                .uri("/internal/v1/cases/" + caseId + "/policy-manifest")
                .header("Authorization", "Bearer " + userToken())
                .exchange()
                .expectStatus()
                .isForbidden()
                .expectBody(String.class)
                .value(response -> assertThat(
                                MAPPER.readTree(response).get("code").stringValue())
                        .isEqualTo("FORBIDDEN_SCOPE"));

        rest.get()
                .uri("/internal/v1/cases/00000000-0000-4000-8000-00000000dead/policy-manifest")
                .header("Authorization", "Bearer " + serviceToken())
                .exchange()
                .expectStatus()
                .isNotFound();

        // A case that predates the table. Answered as 404 rather than back-filled: the payment time the
        // choice would need is not stored on the case, so any back-fill would be a guess.
        jdbc.update("DELETE FROM case_policy_bundle WHERE case_id = ?", caseId);
        jdbc.update("DELETE FROM case_policy_manifest WHERE case_id = ?", caseId);
        rest.get()
                .uri("/internal/v1/cases/" + caseId + "/policy-manifest")
                .header("Authorization", "Bearer " + serviceToken())
                .exchange()
                .expectStatus()
                .isNotFound()
                .expectBody(String.class)
                .value(response -> assertThat(
                                MAPPER.readTree(response).get("message").stringValue())
                        .isEqualTo("this case has no pinned policy manifest"));
    }

    @Test
    @DisplayName("the pinned manifest is written in the same transaction as the case, so neither exists alone")
    void theManifestIsWrittenWithTheCase() {
        JsonNode opened = openCase(nextLine(), "manifest-transaction");
        String caseId = opened.get("case_id").stringValue();

        assertThat(jdbc.queryForObject(
                        "SELECT COUNT(*) FROM case_policy_manifest WHERE case_id = ?", Integer.class, caseId))
                .isEqualTo(1);
        assertThat(manifests.findBundleIds(caseId)).containsExactly("policy-logistics-2026.09");
        PolicyManifestRepository.StoredManifest stored = manifests.findManifest(caseId);
        assertThat(stored.selectedByPaidAt())
                .as("the case records the instant that chose the version, so the choice stays explainable")
                .isEqualTo(PAID_IN_SEPTEMBER);
        assertThat(cases.findCase(caseId)).as("the case itself is there").isNotNull();

        List<String> bundles =
                jdbc.queryForList("SELECT bundle_id FROM case_policy_bundle ORDER BY bundle_id", String.class);
        assertThat(bundles).containsExactly("policy-logistics-2026.09");
    }
}
