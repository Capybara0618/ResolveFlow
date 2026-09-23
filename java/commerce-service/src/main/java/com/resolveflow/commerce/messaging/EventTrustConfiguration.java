package com.resolveflow.commerce.messaging;

import com.resolveflow.shared.core.CoreEnvelope;
import java.security.PublicKey;
import java.util.LinkedHashMap;
import java.util.Map;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;

/**
 * Which producer keys this service trusts (docs/contracts.md:20 — 密钥ID在目标服务信任列表).
 *
 * <p>Verification is not "the signature is valid": it is "the signature is valid <em>and</em> the key that made
 * it is one this service expects to hear from". A verifier that only checked the maths would accept anything
 * signed by any key, including a key an attacker can generate — the signature would prove integrity and
 * nothing about origin.
 *
 * <p>The trust list is keyed by the {@code signing_key_id} carried inside the signed bytes, so a producer
 * cannot change its key id without invalidating its own signature.
 */
@Configuration
public class EventTrustConfiguration {

    /** The consumer name this service's inbox rows are keyed by. */
    public static final String REFUND_COMMAND_CONSUMER = "commerce-refund-command";

    @Bean
    EventVerifier coreEventVerifier(
            @Value("${resolveflow.events.trust.case-service-key-id:case-service-demo-key}") String caseKeyId,
            @Value("${resolveflow.events.trust.case-service-public-key-spki-base64:}") String casePublicKey) {
        Map<String, PublicKey> trusted = new LinkedHashMap<>();
        trusted.put(caseKeyId, loadPublicKey(casePublicKey));
        return new EventVerifier(trusted);
    }

    /**
     * The producer's public key.
     *
     * <p>An empty setting falls back to the corpus fixture key, which exists so the whole path can be run and
     * explained locally — the same position the JWT secret and the signing key take. A deployment supplies its
     * own, and this is the setting that would change when keys are rotated.
     */
    private static PublicKey loadPublicKey(String configured) {
        if (configured == null || configured.isBlank()) {
            return CoreEnvelope.publicKeyFromSpkiBase64(com.resolveflow.shared.core.CoreFixtures.publicKeySpkiBase64());
        }
        return CoreEnvelope.publicKeyFromSpkiBase64(configured);
    }
}
