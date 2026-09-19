package com.resolveflow.shared.security;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

import java.nio.charset.StandardCharsets;
import java.time.Duration;
import java.time.Instant;
import java.util.Base64;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

/**
 * The demonstration JWT verifier's rules, including the ways a token is expected to be refused.
 *
 * <p>Scope is deliberately small (docs/domain-model.md:24: no full IAM): one symmetric algorithm,
 * one user audience, no JWKS, no refresh, no revocation. The negative cases are the point — an
 * "algorithm confusion" token, a service token presented as a user token, a tampered payload and an
 * expired token must each fail for a stated reason rather than being accepted because the signature
 * happened to verify.
 */
class JwtCodecTest {

    private static final String SECRET = "demo-identity-secret-not-a-deployment-key";
    private static final Instant NOW = Instant.parse("2026-09-19T10:00:00Z");

    private static JwtCodec codec() {
        return new JwtCodec(SECRET, Duration.ofHours(1));
    }

    private static AuthenticatedPrincipal principal(String merchant, String customer, Role role) {
        return new AuthenticatedPrincipal("demo-customer", merchant, role, customer);
    }

    @Test
    @DisplayName("a token round-trips into the principal it was issued for")
    void roundTrip() {
        JwtCodec codec = codec();
        String token = codec.issue(principal("M-1001", "C-2002", Role.CUSTOMER), NOW);

        AuthenticatedPrincipal parsed = codec.verifyAsUser(token, NOW);

        assertThat(parsed.subject()).isEqualTo("demo-customer");
        assertThat(parsed.merchantId()).isEqualTo("M-1001");
        assertThat(parsed.customerId()).isEqualTo("C-2002");
        assertThat(parsed.role()).isEqualTo(Role.CUSTOMER);
    }

    @Test
    @DisplayName("the token is a JWS with the documented header and no padding")
    void tokenShapeIsCompactJws() {
        String token = codec().issue(principal("M-1001", "C-2002", Role.CUSTOMER), NOW);
        String[] parts = token.split("\\.");

        assertThat(parts).hasSize(3);
        String header = new String(Base64.getUrlDecoder().decode(parts[0]), StandardCharsets.UTF_8);
        assertThat(header).isEqualTo("{\"alg\":\"HS256\",\"typ\":\"JWT\"}");
        assertThat(token).doesNotContain("=");
    }

    @Test
    @DisplayName("the token carries an expiry and a user audience")
    void claimsCarryExpiryAndAudience() {
        JwtCodec codec = codec();
        String token = codec.issue(principal("M-1001", "C-2002", Role.CUSTOMER), NOW);
        String payload = new String(Base64.getUrlDecoder().decode(token.split("\\.")[1]), StandardCharsets.UTF_8);

        assertThat(payload)
                .contains("\"aud\":\"" + JwtCodec.USER_AUDIENCE + "\"")
                .contains("\"sub\":\"demo-customer\"")
                .contains("\"exp\":")
                .contains("\"iat\":");
    }

    @Test
    @DisplayName("a tampered payload is refused")
    void tamperedPayloadIsRefused() {
        JwtCodec codec = codec();
        String token = codec.issue(principal("M-1001", "C-2002", Role.CUSTOMER), NOW);
        String[] parts = token.split("\\.");
        String forged = Base64.getUrlEncoder()
                .withoutPadding()
                .encodeToString(
                        "{\"sub\":\"demo-customer\",\"merchant_id\":\"M-9999\"}".getBytes(StandardCharsets.UTF_8));
        String tampered = parts[0] + "." + forged + "." + parts[2];

        assertThatThrownBy(() -> codec.verifyAsUser(tampered, NOW))
                .isInstanceOf(JwtCodec.TokenException.class)
                .hasMessageContaining("signature");
    }

    @Test
    @DisplayName("a token signed with another key is refused")
    void foreignKeyIsRefused() {
        String foreign = new JwtCodec("another-demonstration-secret", Duration.ofHours(1))
                .issue(principal("M-1001", "C-2002", Role.CUSTOMER), NOW);

        assertThatThrownBy(() -> codec().verifyAsUser(foreign, NOW))
                .isInstanceOf(JwtCodec.TokenException.class)
                .hasMessageContaining("signature");
    }

    @Test
    @DisplayName("an unsigned token is refused rather than treated as verified")
    void algNoneIsRefused() {
        JwtCodec codec = codec();
        String header = Base64.getUrlEncoder()
                .withoutPadding()
                .encodeToString("{\"alg\":\"none\"}".getBytes(StandardCharsets.UTF_8));
        String payload = Base64.getUrlEncoder()
                .withoutPadding()
                .encodeToString(
                        ("{\"sub\":\"demo-customer\",\"merchant_id\":\"M-1001\",\"role\":\"CUSTOMER\",\"aud\":\""
                                        + JwtCodec.USER_AUDIENCE + "\"}")
                                .getBytes(StandardCharsets.UTF_8));

        assertThatThrownBy(() -> codec.verifyAsUser(header + "." + payload + ".", NOW))
                .isInstanceOf(JwtCodec.TokenException.class)
                .hasMessageContaining("alg");
    }

    @Test
    @DisplayName("a service token cannot be used as a user token")
    void serviceAudienceIsRefusedAsUserToken() {
        JwtCodec codec = codec();
        String serviceToken = codec.issueServiceToken("commerce-service", NOW);

        assertThatThrownBy(() -> codec.verifyAsUser(serviceToken, NOW))
                .isInstanceOf(JwtCodec.TokenException.class)
                .hasMessageContaining("audience");
        assertThat(codec.verifyAsService(serviceToken, NOW).subject()).isEqualTo("commerce-service");
    }

    @Test
    @DisplayName("an expired token is refused, and one expiring later is not")
    void expiryIsEnforced() {
        JwtCodec codec = codec();
        String token = codec.issue(principal("M-1001", "C-2002", Role.CUSTOMER), NOW);

        assertThat(codec.verifyAsUser(token, NOW.plus(Duration.ofMinutes(59))).subject())
                .isEqualTo("demo-customer");
        assertThatThrownBy(() ->
                        codec.verifyAsUser(token, NOW.plus(Duration.ofHours(1)).plusSeconds(1)))
                .isInstanceOf(JwtCodec.TokenException.class)
                .hasMessageContaining("expired");
    }

    @Test
    @DisplayName("a token without the required claims is refused instead of defaulting")
    void missingClaimsAreRefused() {
        JwtCodec codec = codec();
        String missingMerchant = codec.signRaw("{\"sub\":\"demo-customer\",\"role\":\"CUSTOMER\",\"aud\":\""
                + JwtCodec.USER_AUDIENCE + "\",\"exp\":" + (NOW.getEpochSecond() + 600) + "}");

        assertThatThrownBy(() -> codec.verifyAsUser(missingMerchant, NOW))
                .isInstanceOf(JwtCodec.TokenException.class)
                .hasMessageContaining("merchant_id");
    }

    @Test
    @DisplayName("an unknown role is refused rather than mapped to a default")
    void unknownRoleIsRefused() {
        JwtCodec codec = codec();
        String unknownRole =
                codec.signRaw("{\"sub\":\"demo-customer\",\"role\":\"SUPERADMIN\",\"merchant_id\":\"M-1001\",\"aud\":\""
                        + JwtCodec.USER_AUDIENCE + "\",\"exp\":" + (NOW.getEpochSecond() + 600) + "}");

        assertThatThrownBy(() -> codec.verifyAsUser(unknownRole, NOW))
                .isInstanceOf(JwtCodec.TokenException.class)
                .hasMessageContaining("role");
    }

    @Test
    @DisplayName("a bearer header is parsed, and anything else is refused")
    void authorizationHeaderIsParsed() {
        JwtCodec codec = codec();
        String token = codec.issue(principal("M-1001", "C-2002", Role.CUSTOMER), NOW);

        assertThat(codec.principalFromAuthorizationHeader("Bearer " + token, NOW)
                        .merchantId())
                .isEqualTo("M-1001");
        assertThatThrownBy(() -> codec.principalFromAuthorizationHeader(token, NOW))
                .isInstanceOf(JwtCodec.TokenException.class)
                .hasMessageContaining("Bearer");
        assertThatThrownBy(() -> codec.principalFromAuthorizationHeader("", NOW))
                .isInstanceOf(JwtCodec.TokenException.class);
    }

    @Test
    @DisplayName("a merchant-scoped role may not carry a customer identity")
    void roleAndCustomerMustAgree() {
        JwtCodec codec = codec();

        // The principal type refuses to exist in an inconsistent state, so an inconsistent token can
        // never be turned into one. Raw claims are still checked at verification time, because a token
        // is signed by whoever issued it and may simply be wrong.
        assertThatThrownBy(() -> new AuthenticatedPrincipal("demo-reviewer", "M-1001", Role.REVIEWER, "C-2002"))
                .isInstanceOf(IllegalArgumentException.class)
                .hasMessageContaining("customer_id");
        assertThatThrownBy(() -> new AuthenticatedPrincipal("demo-customer", "M-1001", Role.CUSTOMER, null))
                .isInstanceOf(IllegalArgumentException.class)
                .hasMessageContaining("customer_id");

        String reviewerWithCustomer = codec.signRaw(
                "{\"sub\":\"demo-reviewer\",\"role\":\"REVIEWER\",\"merchant_id\":\"M-1001\",\"customer_id\":\"C-2002\",\"aud\":\""
                        + JwtCodec.USER_AUDIENCE + "\",\"exp\":" + (NOW.getEpochSecond() + 600) + "}");
        assertThatThrownBy(() -> codec.verifyAsUser(reviewerWithCustomer, NOW))
                .isInstanceOf(JwtCodec.TokenException.class)
                .hasMessageContaining("customer_id");

        String customerWithoutCustomer =
                codec.signRaw("{\"sub\":\"demo-customer\",\"role\":\"CUSTOMER\",\"merchant_id\":\"M-1001\",\"aud\":\""
                        + JwtCodec.USER_AUDIENCE + "\",\"exp\":" + (NOW.getEpochSecond() + 600) + "}");
        assertThatThrownBy(() -> codec.verifyAsUser(customerWithoutCustomer, NOW))
                .isInstanceOf(JwtCodec.TokenException.class)
                .hasMessageContaining("customer_id");
    }
}
