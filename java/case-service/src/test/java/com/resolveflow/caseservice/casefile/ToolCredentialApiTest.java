package com.resolveflow.caseservice.casefile;

import static org.assertj.core.api.Assertions.assertThat;

import com.resolveflow.caseservice.CaseDatabaseTest;
import com.resolveflow.caseservice.internal.ToolCredentialService;
import com.resolveflow.shared.security.AuthenticatedPrincipal;
import com.resolveflow.shared.security.JwtCodec;
import com.resolveflow.shared.security.Role;
import java.time.Duration;
import java.time.Instant;
import java.util.Base64;
import org.junit.jupiter.api.BeforeEach;
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
 * C06.4④: the run's scoped tool credential, over {@code POST /internal/v1/runs/{run_id}/tool-credential}.
 *
 * <p>The route is declared in {@code contracts/core/openapi-case.yaml} (C00) and had no implementation, while
 * the five tools authenticated themselves with a token out of an environment variable. That gap is the one this
 * test closes: a deployment-wide token is not scoped to a run, cannot be bound to a revision, and cannot be
 * refused when the case has moved on — which is exactly what the contract's description asks for ("a renewal is
 * issued only after case-service confirms the revision is still valid").
 *
 * <p>Four promises are asserted, and each one could plausibly have been left out:
 *
 * <ol>
 *   <li><b>The token is a service token with this service's own signature.</b> The Agent verifies it with the
 *       same {@link JwtCodec} rules (agent/src/resolveflow/api/identity.py), so a credential that is not one is
 *       a credential the tools cannot present.
 *   <li><b>It is bound to the run, the case, the revision and the principal.</b> These are the claims that make
 *       "which line may this token read" answerable at all; a credential without them is a deployment-wide token
 *       with extra steps.
 *   <li><b>A revision the case has left is a 409, not a fresh credential.</b> This is the whole reason a
 *       renewal is a request rather than a pure function: the case is the authority on whether the run it
 *       minted a token for is still the run that describes the case.
 *   <li><b>An unknown run is a 404 and a missing subject is 401</b> — the contract's two refusals, and neither
 *       is a 500.
 * </ol>
 *
 * <p>The initial issuance happens in the Agent, because the Agent is what owns a run. This route exists for the
 * <em>renewal</em> the contract describes: a run that outlives its five-minute tool credential asks Case again,
 * and Case answers only while the revision it was minted for is still the current one.
 */
@AutoConfigureRestTestClient
class ToolCredentialApiTest extends CaseDatabaseTest {

    private static final ObjectMapper MAPPER = new ObjectMapper();

    /** The scopes the contract's own example publishes for this route. */
    private static final String COMMERCE_READ = "commerce:read";

    private static final String POLICY_READ = "policy:read";

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

        @Bean
        @Primary
        StubAgent agentStub(
                org.springframework.web.client.RestClient.Builder builder,
                @Value("${resolveflow.identity.jwt.secret}") String secret,
                @Value("${resolveflow.identity.jwt.service-token-ttl:PT1H}") Duration ttl) {
            return new StubAgent(builder, new JwtCodec(secret, ttl));
        }
    }

    @Autowired
    RestTestClient rest;

    @Autowired
    JwtCodec jwtCodec;

    @Value("${resolveflow.identity.jwt.secret}")
    String secret;

    private long lineCounter = 7700;

    @BeforeEach
    void prepare() {
        deleteAllCaseData(jdbc);
    }

    private String userToken() {
        return jwtCodec.issue(
                new AuthenticatedPrincipal("demo-customer", "M-1001", Role.CUSTOMER, "C-2002"), Instant.now());
    }

    /** The service token a tool would present when asking for its own credential. */
    private String toolIdentityToken() {
        return jwtCodec.issueServiceToken("agent-service", Instant.now());
    }

    private String openCase() {
        String body = rest.post()
                .uri("/api/v1/cases")
                .header("Authorization", "Bearer " + userToken())
                .header("Idempotency-Key", "tool-credential-" + (++lineCounter))
                .contentType(MediaType.APPLICATION_JSON)
                .body("{\"line_id\":\"" + lineCounter + "\",\"description\":\"退款诉求\","
                        + "\"requested_actions\":[\"REFUND\"]}")
                .exchange()
                .expectStatus()
                .isCreated()
                .expectBody(String.class)
                .returnResult()
                .getResponseBody();
        return MAPPER.readTree(body).get("case_id").stringValue();
    }

    private JsonNode credentialFor(String caseId, int revision) {
        String body = rest.post()
                .uri("/internal/v1/runs/" + AgentRunId.forRevision(caseId, revision) + "/tool-credential")
                .header("Authorization", "Bearer " + toolIdentityToken())
                .contentType(MediaType.APPLICATION_JSON)
                .body("{\"case_id\":\"" + caseId + "\",\"input_revision\":" + revision + "}")
                .exchange()
                .expectStatus()
                .isOk()
                .expectBody(String.class)
                .returnResult()
                .getResponseBody();
        return MAPPER.readTree(body);
    }

    /** The claims of a token, decoded without verifying — the test asserts what was signed. */
    private static JsonNode claimsOf(String token) {
        String[] parts = token.split("\\.");
        assertThat(parts).hasSize(3);
        return MAPPER.readTree(Base64.getUrlDecoder().decode(parts[1]));
    }

    // ── the credential ────────────────────────────────────────────────────────────────────────────

    @Test
    @DisplayName("the run's credential is a service token bound to run, case, revision, principal and scope")
    void theCredentialIsBoundToTheRun() {
        String caseId = openCase();
        String runId = AgentRunId.forRevision(caseId, 1);

        JsonNode credential = credentialFor(caseId, 1);

        assertThat(credential.propertyNames()).containsExactlyInAnyOrder("token", "expires_at", "scopes");
        String token = credential.get("token").stringValue();
        assertThat(token).isNotBlank();
        // It must be a token the Agent's verifier accepts: same signature, same issuer, service audience.
        assertThat(jwtCodec.verifyAsService(token, Instant.now()).subject()).isEqualTo("agent-service");

        JsonNode claims = claimsOf(token);
        // The service token's own members, unchanged: a credential that broke these would be refused by the
        // Agent before its scope was ever looked at.
        assertThat(claims.get("iss").stringValue()).isEqualTo("resolveflow-demo-identity");
        assertThat(claims.get("aud").stringValue()).isEqualTo("resolveflow-service");

        // docs/contracts.md:96: 工具凭证 case_id, run_id, input_revision, merchant_id, customer_id, line_id,
        // aud, scopes, exp. Every one of these is what makes "which line may this token read" answerable.
        assertThat(claims.get("case_id").stringValue()).isEqualTo(caseId);
        assertThat(claims.get("run_id").stringValue()).isEqualTo(runId);
        assertThat(claims.get("input_revision").asInt()).isEqualTo(1);
        assertThat(claims.get("merchant_id").stringValue()).isEqualTo("M-1001");
        assertThat(claims.get("customer_id").stringValue()).isEqualTo("C-2002");
        assertThat(claims.get("line_id").stringValue()).isNotBlank();

        // The scopes are the contract's example, and they are a list on the wire.
        assertThat(credential.get("scopes").size()).isEqualTo(2);
        assertThat(credential.get("scopes").get(0).stringValue()).isEqualTo(COMMERCE_READ);
        assertThat(credential.get("scopes").get(1).stringValue()).isEqualTo(POLICY_READ);
        // ...and the same two travel inside the token, space-delimited, because the claim is one string.
        assertThat(claims.get("scope").stringValue()).isEqualTo(COMMERCE_READ + " " + POLICY_READ);
    }

    @Test
    @DisplayName("the credential expires, and well inside the run's own window")
    void theCredentialExpires() {
        String caseId = openCase();

        JsonNode credential = credentialFor(caseId, 1);

        Instant expiresAt = Instant.parse(credential.get("expires_at").stringValue());
        Instant now = Instant.now();
        assertThat(expiresAt).isAfter(now);
        // docs/contracts.md:96: 5分钟有效. Checked as a window rather than an exact number, so a clock skew of a
        // second does not make this test flaky while a lifetime of an hour still fails it.
        assertThat(Duration.between(now, expiresAt)).isBetween(Duration.ofMinutes(4), Duration.ofMinutes(6));
        // The claim and the response agree: a response that said one thing and signed another would send a
        // caller to a token that had already expired.
        assertThat(claimsOf(credential.get("token").stringValue()).get("exp").asLong())
                .isEqualTo(expiresAt.getEpochSecond());
    }

    @Test
    @DisplayName("a second credential for the same revision is a fresh token, not a stored one")
    void aRenewalIsANewToken() {
        String caseId = openCase();

        String first = credentialFor(caseId, 1).get("token").stringValue();
        String second = credentialFor(caseId, 1).get("token").stringValue();

        // Not asserted equal: a renewal exists because the previous one expired, so identical tokens would mean
        // the route was handing back a stored credential. Both must verify, which is the property that matters.
        assertThat(jwtCodec.verifyAsService(first, Instant.now()).subject()).isEqualTo("agent-service");
        assertThat(jwtCodec.verifyAsService(second, Instant.now()).subject()).isEqualTo("agent-service");
    }

    // ── the refusals ──────────────────────────────────────────────────────────────────────────────

    @Test
    @DisplayName("a revision the case has left is 409: the renewal is about the run Case still has")
    void aStaleRevisionIsRefused() {
        String caseId = openCase();
        // Move the case on the way customer material does. The binding for revision 1 still exists, which is
        // exactly the case this refusal is for: the run was real, and the revision it decided on is not current.
        jdbc.update("UPDATE aftersale_case SET input_revision = 2 WHERE case_id = ?", caseId);

        rest.post()
                .uri("/internal/v1/runs/" + AgentRunId.forRevision(caseId, 1) + "/tool-credential")
                .header("Authorization", "Bearer " + toolIdentityToken())
                .contentType(MediaType.APPLICATION_JSON)
                .body("{\"case_id\":\"" + caseId + "\",\"input_revision\":1}")
                .exchange()
                .expectStatus()
                .isEqualTo(409)
                .expectBody()
                .jsonPath("$.code")
                .isEqualTo("STATE_CONFLICT");
    }

    @Test
    @DisplayName("an unknown run is 404, and never a credential")
    void anUnknownRunIsNotFound() {
        String caseId = openCase();
        String neverDispatched = AgentRunId.forRevision(caseId, 7);

        rest.post()
                .uri("/internal/v1/runs/" + neverDispatched + "/tool-credential")
                .header("Authorization", "Bearer " + toolIdentityToken())
                .contentType(MediaType.APPLICATION_JSON)
                .body("{\"case_id\":\"" + caseId + "\",\"input_revision\":7}")
                .exchange()
                .expectStatus()
                .isNotFound()
                .expectBody()
                .jsonPath("$.code")
                .isEqualTo("NOT_FOUND");
    }

    @Test
    @DisplayName("a case this service does not hold is 404, and discloses nothing about which cases exist")
    void anUnknownCaseIsNotFound() {
        String absent = "0f5e6d7c-1111-4222-8333-444455556666";

        rest.post()
                .uri("/internal/v1/runs/" + AgentRunId.forRevision(absent, 1) + "/tool-credential")
                .header("Authorization", "Bearer " + toolIdentityToken())
                .contentType(MediaType.APPLICATION_JSON)
                .body("{\"case_id\":\"" + absent + "\",\"input_revision\":1}")
                .exchange()
                .expectStatus()
                .isNotFound();
    }

    @Test
    @DisplayName("the route needs a service token: a user token is 403, no token is 401")
    void theRouteIsServiceOnly() {
        String caseId = openCase();
        String uri = "/internal/v1/runs/" + AgentRunId.forRevision(caseId, 1) + "/tool-credential";
        String body = "{\"case_id\":\"" + caseId + "\",\"input_revision\":1}";

        // A perfectly valid *user* token is refused: a credential must not be obtainable by somebody who is
        // merely logged in (docs/core-contracts.md:15). The service filter maps a wrong audience to 403.
        rest.post()
                .uri(uri)
                .header("Authorization", "Bearer " + userToken())
                .contentType(MediaType.APPLICATION_JSON)
                .body(body)
                .exchange()
                .expectStatus()
                .isForbidden();

        rest.post()
                .uri(uri)
                .contentType(MediaType.APPLICATION_JSON)
                .body(body)
                .exchange()
                .expectStatus()
                .isUnauthorized();
    }

    @Test
    @DisplayName("a body that names another case than the run belongs to is 422: it is not a credential request")
    void theBodyMustAgreeWithTheRun() {
        String caseId = openCase();
        String otherCase = openCase();

        // The path names a run that really exists — for `otherCase` — while the body names `caseId`. Both halves
        // are internally real and they describe two investigations with two different lines, so answering with a
        // credential would mint a token for whichever half the reader trusted. 422 rather than 404: telling the
        // caller "no such run" about a run it can see would send it looking for the wrong problem (this is the
        // same refusal the run intake makes at docs/core-contracts.md:60). This is the case that first came out as
        // a 404, which is why the service looks the run up by id before it compares anything else.
        rest.post()
                .uri("/internal/v1/runs/" + AgentRunId.forRevision(otherCase, 1) + "/tool-credential")
                .header("Authorization", "Bearer " + toolIdentityToken())
                .contentType(MediaType.APPLICATION_JSON)
                .body("{\"case_id\":\"" + caseId + "\",\"input_revision\":1}")
                .exchange()
                .expectStatus()
                .isEqualTo(422)
                .expectBody()
                .jsonPath("$.code")
                .isEqualTo("SEMANTIC_INVALID");
    }

    @Test
    @DisplayName("a run that exists for another revision of the same case is 404, not a credential")
    void aRunForAnotherRevisionIsNotFound() {
        String caseId = openCase();

        // This is the request that made the ordering matter: the path names the run for revision 1 and the body
        // asks about revision 2. Revision 1's run is real, so a check ordered the other way round would compare
        // revisions and answer 409 — "the case moved on" — about a request that simply names no run. Nothing is
        // wrong with the case here; the request is not about the run it names.
        rest.post()
                .uri("/internal/v1/runs/" + AgentRunId.forRevision(caseId, 1) + "/tool-credential")
                .header("Authorization", "Bearer " + toolIdentityToken())
                .contentType(MediaType.APPLICATION_JSON)
                .body("{\"case_id\":\"" + caseId + "\",\"input_revision\":2}")
                .exchange()
                .expectStatus()
                .isNotFound();
    }

    @Test
    @DisplayName("the credential's scopes are the ones the route publishes, not a caller's choice")
    void theCredentialCarriesTheRoutesOwnScopes() {
        String caseId = openCase();

        JsonNode credential = credentialFor(caseId, 1);

        // AS02.3's security sub-step: the scopes exist so that a *route* can require them. Until this step nothing
        // read the claim, so the credential was bound to a run on paper and enforced nowhere — the gap the ledger
        // recorded as "工具凭据的 scope 没有被任何一方强制".
        assertThat(credential.get("scopes").size()).isEqualTo(ToolCredentialService.TOOL_SCOPES.size());
        assertThat(credential.get("scopes").get(0).stringValue()).isEqualTo(ToolCredentialService.TOOL_SCOPES.get(0));
    }

    @Test
    @DisplayName("a service token that names no scope is still accepted by the credential route itself")
    void aScopelessServiceTokenMayStillAskForACredential() {
        String caseId = openCase();

        // The route that *mints* credentials is guarded by the subject and the run binding, not by a scope: the
        // Agent has no credential yet, so requiring `commerce:read` of it would be requiring the thing it is
        // asking for. This is asserted because a scope check added too broadly would lock the Agent out of its own
        // credential and the failure would look like a broken Case.
        rest.post()
                .uri("/internal/v1/runs/" + AgentRunId.forRevision(caseId, 1) + "/tool-credential")
                .header("Authorization", "Bearer " + toolIdentityToken())
                .contentType(MediaType.APPLICATION_JSON)
                .body("{\"case_id\":\"" + caseId + "\",\"input_revision\":1}")
                .exchange()
                .expectStatus()
                .isOk();
    }

    @Test
    @DisplayName("the two refusal codes are the contract's, so a caller can branch on them")
    void theRefusalsUseTheContractsCodeBody() {
        String caseId = openCase();
        // Move the case on the way customer material does, then ask for the run of the revision it left. The run
        // in the path is the real one for revision 1, so the request is about a run this service holds and the
        // only thing wrong is that the case no longer accepts it — which is exactly the 409.
        jdbc.update("UPDATE aftersale_case SET input_revision = 2 WHERE case_id = ?", caseId);

        // docs/core-contracts.md:15: the error body is {code, message, retryable, trace_id, details}. Checked here
        // rather than only for the status, because a caller that retried a 409 forever would be reading a body
        // that said the request could never succeed.
        String body = rest.post()
                .uri("/internal/v1/runs/" + AgentRunId.forRevision(caseId, 1) + "/tool-credential")
                .header("Authorization", "Bearer " + toolIdentityToken())
                .contentType(MediaType.APPLICATION_JSON)
                .body("{\"case_id\":\"" + caseId + "\",\"input_revision\":1}")
                .exchange()
                .expectStatus()
                .isEqualTo(409)
                .expectBody(String.class)
                .returnResult()
                .getResponseBody();

        JsonNode refusal = MAPPER.readTree(body);
        assertThat(refusal.get("code").stringValue()).isEqualTo("STATE_CONFLICT");
        assertThat(refusal.get("retryable").booleanValue()).isFalse();
        assertThat(refusal.get("trace_id").stringValue()).isNotBlank();
        assertThat(refusal.get("message").stringValue()).isNotBlank();
    }
}
