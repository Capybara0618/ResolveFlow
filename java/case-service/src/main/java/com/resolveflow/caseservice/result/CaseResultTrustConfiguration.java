package com.resolveflow.caseservice.result;

import com.resolveflow.shared.core.CoreEnvelope;
import java.security.PublicKey;
import java.util.LinkedHashMap;
import java.util.Map;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;

/**
 * Which producer keys this service trusts for results (docs/contracts.md:20 — 密钥ID在目标服务信任列表).
 *
 * <p>The mirror of Commerce's {@code EventTrustConfiguration}, and the mirror is the point: a consumer that
 * only checked that a signature was mathematically valid would accept a document signed by a key it has never
 * heard of — the signature would prove integrity and nothing at all about origin. Case-service therefore
 * trusts exactly the key id Commerce signs its results with, and the key id travels inside the signed bytes, so
 * a producer cannot re-attribute its own message without invalidating it.
 *
 * <p>An empty public-key setting falls back to the corpus fixture key, exactly as the outbox writer's signing
 * key does (C05.1a): the whole path can then be run and explained locally, and a deployment supplies its own.
 * The two settings are separate from the signing settings because these are *the other service's* key and id,
 * not this service's.
 */
@Configuration
public class CaseResultTrustConfiguration {

    /** The consumer name this service's result-inbox rows are keyed by. */
    public static final String RESULT_CONSUMER = "case-refund-result";

    @Bean
    CaseResultVerifier caseResultVerifier(
            @Value("${resolveflow.events.trust.commerce-service-key-id:commerce-service-demo-key}") String keyId,
            @Value("${resolveflow.events.trust.commerce-service-public-key-spki-base64:}") String publicKey) {
        Map<String, PublicKey> trusted = new LinkedHashMap<>();
        trusted.put(keyId, loadPublicKey(publicKey));
        return new CaseResultVerifier(trusted);
    }

    private static PublicKey loadPublicKey(String configured) {
        if (configured == null || configured.isBlank()) {
            return CoreEnvelope.publicKeyFromSpkiBase64(com.resolveflow.shared.core.CoreFixtures.publicKeySpkiBase64());
        }
        return CoreEnvelope.publicKeyFromSpkiBase64(configured);
    }
}
