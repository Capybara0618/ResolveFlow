package com.resolveflow.caseservice.casefile;

import static org.assertj.core.api.Assertions.assertThat;

import com.resolveflow.caseservice.CaseDatabaseTest;
import com.resolveflow.shared.security.AuthenticatedPrincipal;
import com.resolveflow.shared.security.JwtCodec;
import com.resolveflow.shared.security.Role;
import com.resolveflow.shared.security.ServiceScopes;
import java.time.Duration;
import java.time.Instant;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
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

/**
 * AS02.3's security sub-step on Case's side: the policy routes require {@code policy:read}.
 *
 * <p>Commerce's half of this step is {@code InternalScopeEnforcementTest}; this is the other half, and it exists
 * separately because {@code policy:read} is the scope Case <em>mints</em> onto a run's tool credential and therefore
 * the one most likely to stay decorative. C06.4④ put both scopes on the credential and nothing read either, so
 * {@code docs/core-contracts.md:74}'s binding was enforced nowhere; the ledger recorded that as a gap rather than
 * letting "凭据已实现" be read as "权限已执行".
 *
 * <p>What the five whitelisted tools read policy <em>through</em> is exactly two routes — the manifest a case is
 * pinned to, and the authoritative bundle text a citation is checked against — and both are reads, so one scope
 * covers them ({@code docs/agent-spec.md:26-32}). The assertions below are the pair, because only the pair is
 * evidence: a filter that refused every token would satisfy the refusal cases alone, so the accepted read is what
 * shows the scope is being read rather than the route being broken.
 *
 * <p>This class lives in {@code casefile} rather than beside {@code PolicyApiTest} because it opens a real case,
 * and the stubs that make that possible ({@link StubCommerce}, {@link StubAgent}) are package-private here. Widening
 * them so a test could sit in another package would trade a real encapsulation for a directory layout.
 *
 * <p>{@code CaseDatabaseTest} already declares {@code webEnvironment = RANDOM_PORT}, so a servlet filter is
 * genuinely in the request path here. That detail is load-bearing and was the first draft's bug on the Commerce
 * side: a MOCK web environment installs no container, runs no filter, and makes every refusal assertion pass for
 * the wrong reason — or, as happened there, fail with {@code 200}.
 */
@AutoConfigureRestTestClient
class CaseScopeEnforcementTest extends CaseDatabaseTest {

    @TestConfiguration
    static class StubUpstreamsConfiguration {

        @Bean
        @Primary
        StubCommerce commerceStub(
                org.springframework.web.client.RestClient.Builder builder,
                @Value("${resolveflow.identity.jwt.secret}") String secret,
                @Value("${resolveflow.identity.jwt.service-token-ttl:PT1H}") Duration ttl) {
            return new StubCommerce(builder, new JwtCodec(secret, ttl));
        }

        @Bean
        @Primary
        StubAgent agentStub(
                org.springframework.web.client.RestClient.Builder builder,
                @Value("${resolveflow.identity.jwt.secret}") String secret,
                @Value("${resolveflow.identity.jwt.service-token-ttl:PT1H}") Duration ttl) {
            return new StubAgent(builder, new JwtCodec(secret, ttl));
        }
    }

    private static final ObjectMapper MAPPER = new ObjectMapper();

    /** A bundle {@code CaseDatabaseTest} installs from the repository's own fixtures for every test class. */
    private static final String BUNDLE = "policy-logistics-2026.09";

    @Autowired
    RestTestClient rest;

    @Autowired
    JwtCodec codec;

    private String tokenWith(String scope) {
        return codec.issueServiceToken("agent-service", null, null, scope, Instant.now());
    }

    private String userToken() {
        return codec.issue(
                new AuthenticatedPrincipal("demo-customer", "M-1001", Role.CUSTOMER, "C-2002"), Instant.now());
    }

    // ── the authoritative policy text needs policy:read ───────────────────────────────────────────

    @Test
    @DisplayName("a token holding policy:read may read the authoritative policy text")
    void theRightScopeIsAccepted() {
        rest.get()
                .uri("/internal/v1/policies/" + BUNDLE)
                .header("Authorization", "Bearer " + tokenWith(ServiceScopes.POLICY_READ))
                .exchange()
                .expectStatus()
                .isOk();
    }

    @Test
    @DisplayName("a token holding only commerce:read is refused: the two halves of the credential are not one key")
    void theOtherHalfOfTheCredentialIsRefused() {
        // This is the assertion that makes the step real rather than decorative. A run's credential carries BOTH
        // scopes, so every test that presents the real credential passes either way; this presents the same token
        // shape with only Commerce's half, and Case must not accept it. Before this step it did.
        String body = rest.get()
                .uri("/internal/v1/policies/" + BUNDLE)
                .header("Authorization", "Bearer " + tokenWith(ServiceScopes.COMMERCE_READ))
                .exchange()
                .expectStatus()
                .isForbidden()
                .expectBody(String.class)
                .returnResult()
                .getResponseBody();

        // The contract's scope refusal, so a caller can branch on the code rather than the prose
        // (docs/core-contracts.md:15).
        assertThat(body).contains("FORBIDDEN_SCOPE");
    }

    @Test
    @DisplayName("a scope-less service token is refused on the policy routes")
    void aScopelessServiceTokenIsRefused() {
        // The interesting half of the coupling: Case's *own* internal callers present scope-less tokens, and three
        // of its internal routes are deliberately unscoped (the credential mint, the callback, the evidence
        // read). The policy routes are not among them, so a scope-less token must be refused rather than
        // grandfathered in for being "internal".
        rest.get()
                .uri("/internal/v1/policies/" + BUNDLE)
                .header("Authorization", "Bearer " + codec.issueServiceToken("agent-service", Instant.now()))
                .exchange()
                .expectStatus()
                .isForbidden();
    }

    // ── the pinned manifest needs policy:read, and only when the route really is that route ────────

    @Test
    @DisplayName("the pinned policy manifest needs policy:read")
    void theManifestRouteIsScoped() {
        String caseId = openCase();
        rest.get()
                .uri("/internal/v1/cases/" + caseId + "/policy-manifest")
                .header("Authorization", "Bearer " + tokenWith(ServiceScopes.COMMERCE_READ))
                .exchange()
                .expectStatus()
                .isForbidden();
        // ...and is readable with the scope it asks for, so the refusal above is about the scope and not about the
        // route being broken or the case being unknown.
        rest.get()
                .uri("/internal/v1/cases/" + caseId + "/policy-manifest")
                .header("Authorization", "Bearer " + tokenWith(ServiceScopes.POLICY_READ))
                .exchange()
                .expectStatus()
                .isOk();
    }

    @Test
    @DisplayName("scoping the manifest does not scope its sibling under the same prefix")
    void theSiblingRouteUnderTheSamePrefixStaysUnscoped() {
        // PolicyManifestController, CaseEvidenceInternalController and AgentCallbackController all map under
        // /internal/v1/cases. A prefix-based rule would have made "read the pinned policy" and "read the case's
        // evidence" the same permission, so the filter matches the manifest by its path segment instead. This pins
        // that the distinction holds: the evidence read is reachable by the same scope-less service token it
        // accepted before this step, which is what keeps the change from being a blanket tightening of the
        // internal surface.
        String caseId = openCase();
        rest.get()
                .uri("/internal/v1/cases/" + caseId + "/evidence")
                .header("Authorization", "Bearer " + codec.issueServiceToken("agent-service", Instant.now()))
                .exchange()
                .expectStatus()
                .isOk();
    }

    @Test
    @DisplayName("a user token is still refused on the policy routes")
    void aUserTokenIsStillNotAServiceToken() {
        // Re-asserted because this step touches the same filter: a valid user token has its own audience, and the
        // audience check must keep firing. The refusal is 403 FORBIDDEN_SCOPE, the contract's "wrong kind of token"
        // answer, rather than 401 — "somebody is logged in" is not the test for a service surface.
        rest.get()
                .uri("/internal/v1/policies/" + BUNDLE)
                .header("Authorization", "Bearer " + userToken())
                .exchange()
                .expectStatus()
                .isForbidden();
    }

    @Test
    @DisplayName("both scopes in one claim, space-delimited, is the shape the credential really has")
    void theRealCredentialShapeIsAccepted() {
        // The tool credential carries `commerce:read policy:read` as a single space-delimited claim (RFC 6749's
        // spelling), so enforcement has to split it rather than compare the whole claim against one name. A filter
        // that understood only a single scope would refuse the very credential C06.4④ mints — which is the failure
        // that would matter most in production and the least visible in a unit test.
        rest.get()
                .uri("/internal/v1/policies/" + BUNDLE)
                .header(
                        "Authorization",
                        "Bearer " + tokenWith(ServiceScopes.COMMERCE_READ + " " + ServiceScopes.POLICY_READ))
                .exchange()
                .expectStatus()
                .isOk();
    }

    /** Opens a real case through the public API and returns its id, so the manifest route has something to answer. */
    private String openCase() {
        String body = rest.post()
                .uri("/api/v1/cases")
                .header("Authorization", "Bearer " + userToken())
                .header("Idempotency-Key", "case-scope-" + System.nanoTime())
                .contentType(MediaType.APPLICATION_JSON)
                // This class shares the module's MySQL container; a modulo-800 line id can collide with
                // another test's still-open slot and turn a scope assertion into an unrelated 409.
                .body("{\"line_id\":\"scope-" + java.util.UUID.randomUUID() + "\","
                        + "\"description\":\"退款诉求\",\"requested_actions\":[\"REFUND\"]}")
                .exchange()
                .expectStatus()
                .isCreated()
                .expectBody(String.class)
                .returnResult()
                .getResponseBody();
        JsonNode created = MAPPER.readTree(body);
        return created.get("case_id").stringValue();
    }
}
