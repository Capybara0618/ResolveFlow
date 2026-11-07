package com.resolveflow.commerce.internal;

import static org.assertj.core.api.Assertions.assertThat;

import com.resolveflow.commerce.CommerceDatabaseTest;
import com.resolveflow.shared.security.JwtCodec;
import java.time.Duration;
import java.time.Instant;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.resttestclient.autoconfigure.AutoConfigureRestTestClient;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.test.web.servlet.client.RestTestClient;

/**
 * AS02.3's security sub-step: the {@code /internal/**} surface enforces the **scope** a token carries.
 *
 * <p>Before this step the filter verified the signature and the audience and nothing else, so a token minted for
 * one purpose could read every internal route. That mattered because C06.4④ mints a run-scoped tool credential
 * carrying {@code commerce:read policy:read} precisely so that a route can require them — the ledger recorded the
 * gap as *"工具凭据的 scope 没有被任何一方强制…否则'凭据已实现'会被读成'权限已执行'"*, and
 * {@code docs/core-contracts.md:74} states the scope is part of the credential's binding.
 *
 * <p>What is asserted is the pair, because only the pair is evidence: a filter that refused everything would pass
 * the negative case alone, and the positive case is what shows the scope is being read rather than the route being
 * broken. Both are asked of the **same** route with the **same** token shape — only the scope differs.
 *
 * <p><b>{@code webEnvironment = RANDOM_PORT} is load-bearing here.</b> The first draft of this test omitted it and
 * its four negative cases all returned {@code 200}: {@code CommerceDatabaseTest}'s {@code @SpringBootTest} defaults
 * to a MOCK web environment, which installs no servlet container and therefore never runs a servlet filter, so
 * every request reached the controller unauthenticated. The scope check was never the thing being tested. A real
 * port is what makes {@code ServiceTokenFilter} part of the request at all.
 */
@SpringBootTest(webEnvironment = SpringBootTest.WebEnvironment.RANDOM_PORT)
@AutoConfigureRestTestClient
class InternalScopeEnforcementTest extends CommerceDatabaseTest {

    /** A line the seed gives a shipment, so the route under test answers about real data. */
    private static final String LINE = "7001";

    @Autowired
    RestTestClient rest;

    @Autowired
    JwtCodec codec;

    private String tokenWith(String scope) {
        return codec.issueServiceToken("agent-service", null, null, scope, Instant.now());
    }

    // ── the commerce read route needs commerce:read ────────────────────────────────────────────────

    @Test
    @DisplayName("a token holding commerce:read may read a line's context")
    void theRightScopeIsAccepted() {
        rest.get()
                .uri("/internal/v1/order-lines/" + LINE + "/context")
                .header("Authorization", "Bearer " + tokenWith("commerce:read"))
                .exchange()
                .expectStatus()
                .isOk();
    }

    @Test
    @DisplayName("a token holding only policy:read is refused: the scope is enforced, not decorative")
    void theWrongScopeIsRefused() {
        // The exact credential a run holds is split across two ownerships: Commerce's data needs `commerce:read`
        // and Case's policy needs `policy:read`. A token that carries only the second must not read the first —
        // which is the whole reason the claim is on the token at all.
        String body = rest.get()
                .uri("/internal/v1/order-lines/" + LINE + "/context")
                .header("Authorization", "Bearer " + tokenWith("policy:read"))
                .exchange()
                .expectStatus()
                .isForbidden()
                .expectBody(String.class)
                .returnResult()
                .getResponseBody();

        // The contract's scope refusal, so a caller can branch on the code rather than on the prose
        // (docs/core-contracts.md:15).
        assertThat(body).contains("FORBIDDEN_SCOPE");
    }

    @Test
    @DisplayName("a token holding no scope at all is refused on a scoped route")
    void aScopelessTokenIsRefused() {
        // This is the case that made the change safe to make: Case's own internal calls present tokens without a
        // scope (CommerceOrderLineClient issues them with {@code iss}/{@code aud}/{@code sub} only). Requiring a
        // scope here therefore *breaks* those calls until Case asks for one, which is a real coupling and the
        // reason this test exists: it pins the behaviour so the coupling cannot be forgotten.
        rest.get()
                .uri("/internal/v1/order-lines/" + LINE + "/context")
                .header("Authorization", "Bearer " + codec.issueServiceToken("case-service", Instant.now()))
                .exchange()
                .expectStatus()
                .isForbidden();
    }

    @Test
    @DisplayName("a user token is still refused with 403 and not treated as a scoped caller")
    void aUserTokenIsStillNotAServiceToken() {
        // The pre-existing boundary, re-asserted here because this step touches the same filter: a valid user token
        // has an audience of its own, and the audience check must still fire before any scope reasoning.
        String userToken = codec.issue(
                new com.resolveflow.shared.security.AuthenticatedPrincipal(
                        "demo-customer",
                        null,
                        com.resolveflow.shared.security.Role.CUSTOMER,
                        "B-legacy-60865438438feefa1dfbc0ce3d07ba2cb1b09a80"),
                Instant.now());

        rest.get()
                .uri("/internal/v1/order-lines/" + LINE + "/context")
                .header("Authorization", "Bearer " + userToken)
                .exchange()
                .expectStatus()
                .isForbidden();
    }

    @Test
    @DisplayName("the TTL the test mints with is irrelevant here, but a bad signature is still 401")
    void aForgedSignatureIsUnauthenticated() {
        String forged = tokenWith("commerce:read");
        String tampered = forged.substring(0, forged.length() - 4) + "AAAA";

        rest.get()
                .uri("/internal/v1/order-lines/" + LINE + "/context")
                .header("Authorization", "Bearer " + tampered)
                .exchange()
                .expectStatus()
                .isUnauthorized();
    }

    @Test
    @DisplayName("the scope claim travels as a space-delimited string, which is what the mint writes")
    void multipleScopesAreOneDelimitedClaim() {
        // The credential carries two scopes and the JWT `scope` claim is a single string (RFC 6749's spelling), so
        // the enforcement has to split it rather than compare the whole claim to one name. A filter that only
        // understood a single scope would refuse the very credential C06.4④ mints.
        rest.get()
                .uri("/internal/v1/order-lines/" + LINE + "/context")
                .header("Authorization", "Bearer " + tokenWith("commerce:read policy:read"))
                .exchange()
                .expectStatus()
                .isOk();
    }

    @Test
    @DisplayName("the codec reports the scope claim, which is what made enforcement possible at all")
    void theCodecCarriesTheScope() {
        // `ServiceIdentity` used to hold only the subject, so no filter *could* check a scope. This asserts the
        // value reaches the caller, and is the unit-level half of the route tests above.
        assertThat(codec.verifyAsService(tokenWith("commerce:read policy:read"), Instant.now())
                        .scope())
                .isEqualTo("commerce:read policy:read");
        assertThat(codec.verifyAsService(codec.issueServiceToken("case-service", Instant.now()), Instant.now())
                        .scope())
                .isNull();
    }

    @Test
    @DisplayName("the issued token really expires, so the test's ttl is not accidentally infinite")
    void theTokenExpires() {
        // A guard for the fixture rather than for the code: if the codec were minting non-expiring tokens, every
        // refusal test above could pass for the wrong reason.
        Duration ttl = codec.timeToLive();
        assertThat(ttl).isPositive();
        assertThat(ttl).isLessThanOrEqualTo(Duration.ofDays(1));
    }
}
