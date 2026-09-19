package com.resolveflow.shared.security;

import java.nio.charset.StandardCharsets;
import java.security.GeneralSecurityException;
import java.security.MessageDigest;
import java.time.Duration;
import java.time.Instant;
import java.util.Base64;
import java.util.Map;
import javax.crypto.Mac;
import javax.crypto.spec.SecretKeySpec;
import tools.jackson.databind.JsonNode;
import tools.jackson.databind.ObjectMapper;

/**
 * The demonstration JWT codec: HS256, one user audience, one service audience.
 *
 * <p>docs/core-contracts.md:15 asks for an {@code Authorization: JWT} user token and a separate
 * service token with its own {@code aud}/scope. This class is deliberately small and explicit about
 * what it does <em>not</em> do — no JWKS, no key rotation, no RS256, no refresh tokens, no revocation
 * list — because the project has no full IAM (docs/domain-model.md:24) and a half-configured
 * "production" auth stack would be worse evidence than an honest demonstration one.
 *
 * <p>The algorithm is fixed rather than read from the token: a verifier that honours the token's own
 * {@code alg} is how "alg: none" and RS256/HS256 confusion attacks work, so anything other than
 * {@code HS256} is refused before the signature is even examined.
 *
 * <p>Every claim needed to decide visibility is required, and every failure is a
 * {@link TokenException} naming the rule that refused it, so a caller cannot be left wondering
 * whether a token was rejected for a real reason or silently defaulted.
 */
public final class JwtCodec {

    /** Audience of a token a user presents to the public surface. */
    public static final String USER_AUDIENCE = "resolveflow-user";

    /** Audience of a service-to-service token; never accepted on the public surface. */
    public static final String SERVICE_AUDIENCE = "resolveflow-service";

    public static final String ISSUER = "resolveflow-demo-identity";

    private static final String ALGORITHM = "HS256";
    private static final String MAC_ALGORITHM = "HmacSHA256";
    private static final String HEADER_JSON = "{\"alg\":\"HS256\",\"typ\":\"JWT\"}";
    private static final ObjectMapper MAPPER = new ObjectMapper();
    private static final Base64.Encoder ENCODER = Base64.getUrlEncoder().withoutPadding();
    private static final Base64.Decoder DECODER = Base64.getUrlDecoder();

    private final byte[] secret;
    private final Duration timeToLive;

    public JwtCodec(String secret, Duration timeToLive) {
        if (secret == null || secret.length() < 16) {
            throw new IllegalArgumentException("the demonstration signing secret must be at least 16 characters");
        }
        if (timeToLive == null || timeToLive.isZero() || timeToLive.isNegative()) {
            throw new IllegalArgumentException("token lifetime must be positive");
        }
        if (timeToLive.getSeconds() > 86400) {
            // The core OpenAPI caps expires_in at 86400; a longer token could not be described by it.
            throw new IllegalArgumentException("token lifetime must not exceed 86400 seconds");
        }
        this.secret = secret.getBytes(StandardCharsets.UTF_8);
        this.timeToLive = timeToLive;
    }

    /** Raised when a token is missing, malformed, or fails a stated rule. */
    public static class TokenException extends IllegalArgumentException {

        private static final long serialVersionUID = 1L;

        public TokenException(String message) {
            super(message);
        }

        public TokenException(String message, Throwable cause) {
            super(message, cause);
        }
    }

    public Duration timeToLive() {
        return timeToLive;
    }

    /** Issue a user token for a verified principal. */
    public String issue(AuthenticatedPrincipal principal, Instant now) {
        var claims = MAPPER.createObjectNode();
        claims.put("sub", principal.subject());
        claims.put("merchant_id", principal.merchantId());
        claims.put("role", principal.role().name());
        if (principal.customerId() != null) {
            claims.put("customer_id", principal.customerId());
        }
        claims.put("aud", USER_AUDIENCE);
        claims.put("iss", ISSUER);
        claims.put("iat", now.getEpochSecond());
        claims.put("exp", now.plus(timeToLive).getEpochSecond());
        return signRaw(claims.toString());
    }

    /** Issue a service token: same signature, different audience and no user identity. */
    public String issueServiceToken(String serviceName, Instant now) {
        if (serviceName == null || serviceName.isBlank()) {
            throw new TokenException("a service token needs a service name");
        }
        var claims = MAPPER.createObjectNode();
        claims.put("sub", serviceName);
        claims.put("aud", SERVICE_AUDIENCE);
        claims.put("iss", ISSUER);
        claims.put("iat", now.getEpochSecond());
        claims.put("exp", now.plus(timeToLive).getEpochSecond());
        return signRaw(claims.toString());
    }

    /**
     * Sign an arbitrary claims object.
     *
     * <p>Used by the seeder and by the tests that have to produce a token no honest issuer would
     * (missing claims, an unknown role); production paths reach the same signature through
     * {@link #issue}.
     */
    public String signRaw(String claimsJson) {
        String payload = ENCODER.encodeToString(claimsJson.getBytes(StandardCharsets.UTF_8));
        String signingInput = ENCODER.encodeToString(HEADER_JSON.getBytes(StandardCharsets.UTF_8)) + "." + payload;
        return signingInput + "." + ENCODER.encodeToString(hmac(signingInput));
    }

    /** Verify a user token and return the principal it carries. */
    public AuthenticatedPrincipal verifyAsUser(String token, Instant now) {
        JsonNode claims = verifiedClaims(token, USER_AUDIENCE, now);
        String subject = requiredText(claims, "sub");
        String merchant = requiredText(claims, "merchant_id");
        String roleText = requiredText(claims, "role");
        Role role;
        try {
            role = Role.valueOf(roleText);
        } catch (IllegalArgumentException error) {
            throw new TokenException("unknown role '" + roleText + "'; the token's role decides visibility");
        }
        JsonNode customer = claims.get("customer_id");
        String customerId = customer == null || customer.isNull() ? null : customer.stringValue();
        try {
            return new AuthenticatedPrincipal(subject, merchant, role, customerId);
        } catch (IllegalArgumentException error) {
            throw new TokenException("customer_id does not match the role: " + error.getMessage());
        }
    }

    /** Verify a service token; a user token is not one, and vice versa. */
    public ServiceIdentity verifyAsService(String token, Instant now) {
        JsonNode claims = verifiedClaims(token, SERVICE_AUDIENCE, now);
        return new ServiceIdentity(requiredText(claims, "sub"));
    }

    /** Read a principal straight from an {@code Authorization} header. */
    public AuthenticatedPrincipal principalFromAuthorizationHeader(String header, Instant now) {
        if (header == null || !header.startsWith("Bearer ")) {
            throw new TokenException("Authorization must be 'Bearer <jwt>'");
        }
        String token = header.substring("Bearer ".length()).trim();
        if (token.isEmpty()) {
            throw new TokenException("Authorization must be 'Bearer <jwt>'");
        }
        return verifyAsUser(token, now);
    }

    private JsonNode verifiedClaims(String token, String expectedAudience, Instant now) {
        if (token == null || token.isBlank()) {
            throw new TokenException("no token supplied");
        }
        String[] parts = token.split("\\.", -1);
        if (parts.length != 3) {
            throw new TokenException("a token must have three dot-separated parts");
        }
        JsonNode header = decodeJson(parts[0], "header");
        // The algorithm is pinned here rather than trusted from the token.
        if (!header.has("alg") || !ALGORITHM.equals(header.get("alg").stringValue())) {
            throw new TokenException("alg must be " + ALGORITHM + "; unsigned or other-algorithm tokens are refused");
        }
        if (parts[2].isEmpty()) {
            throw new TokenException("signature is missing");
        }
        byte[] presented;
        try {
            presented = DECODER.decode(parts[2]);
        } catch (IllegalArgumentException error) {
            throw new TokenException("signature is not valid base64url", error);
        }
        if (!MessageDigest.isEqual(hmac(parts[0] + "." + parts[1]), presented)) {
            throw new TokenException("signature does not cover this token");
        }
        JsonNode claims = decodeJson(parts[1], "payload");
        JsonNode audience = claims.get("aud");
        if (audience == null || !expectedAudience.equals(audience.stringValue())) {
            String found = audience == null ? "none" : audience.stringValue();
            throw new TokenException("audience must be " + expectedAudience + ", found " + found);
        }
        JsonNode expiry = claims.get("exp");
        if (expiry == null || !expiry.isNumber()) {
            throw new TokenException("token has no exp");
        }
        Instant expiresAt = Instant.ofEpochSecond(expiry.asLong());
        if (!now.isBefore(expiresAt)) {
            throw new TokenException("token expired at " + expiresAt);
        }
        JsonNode notBefore = claims.get("nbf");
        if (notBefore != null && notBefore.isNumber() && now.isBefore(Instant.ofEpochSecond(notBefore.asLong()))) {
            throw new TokenException("token is not valid yet");
        }
        return claims;
    }

    private static String requiredText(JsonNode claims, String member) {
        JsonNode value = claims.get(member);
        if (value == null
                || value.isNull()
                || !value.isString()
                || value.stringValue().isBlank()) {
            throw new TokenException("token is missing " + member);
        }
        return value.stringValue();
    }

    private static JsonNode decodeJson(String part, String what) {
        try {
            return MAPPER.readTree(new String(DECODER.decode(part), StandardCharsets.UTF_8));
        } catch (RuntimeException error) {
            throw new TokenException("token " + what + " is not valid JSON", error);
        }
    }

    private byte[] hmac(String signingInput) {
        try {
            Mac mac = Mac.getInstance(MAC_ALGORITHM);
            mac.init(new SecretKeySpec(secret, MAC_ALGORITHM));
            return mac.doFinal(signingInput.getBytes(StandardCharsets.UTF_8));
        } catch (GeneralSecurityException error) {
            throw new TokenException("HS256 signing failed", error);
        }
    }

    /** The identity a service token carries: no merchant, no role, no customer. */
    public record ServiceIdentity(String subject) {

        public ServiceIdentity {
            if (subject == null || subject.isBlank()) {
                throw new IllegalArgumentException("a service identity needs a subject");
            }
        }

        /** Scopes are carried by the audience; the demonstration has exactly two. */
        public Map<String, String> audiences() {
            return Map.of("aud", SERVICE_AUDIENCE);
        }
    }
}
