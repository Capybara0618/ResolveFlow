package com.resolveflow.shared.contract;

import java.security.GeneralSecurityException;
import java.security.KeyFactory;
import java.security.PrivateKey;
import java.security.PublicKey;
import java.security.Signature;
import java.security.spec.PKCS8EncodedKeySpec;
import java.security.spec.X509EncodedKeySpec;
import java.util.Base64;
import java.util.List;
import tools.jackson.databind.JsonNode;
import tools.jackson.databind.ObjectMapper;

/**
 * Event envelope signing input and Ed25519 signatures.
 *
 * <p>docs/contracts.md:17 fixes the rule: sign the canonicalised envelope with the {@code signature}
 * field excluded and {@code signing_key_id} retained, using Ed25519. T02 must freeze both the input
 * and the resulting bytes with a cross-language test, which is what this class and {@code
 * resolveflow.contracts.events} jointly do against {@code contracts/fixtures/expected-hashes.json}.
 *
 * <p>Two rules here are load-bearing:
 *
 * <ul>
 *   <li>The signing input is <em>normalised</em>, not "whatever was on the wire". Optional members
 *       that are absent become JSON {@code null} before canonicalisation, so a producer that omits
 *       {@code traceparent} and a producer that sends {@code "traceparent": null} sign identical
 *       bytes. Without this, Java and Python would each be self-consistent and still disagree in
 *       production.
 *   <li>The signature is not an authentication credential by itself. docs/contracts.md:127 requires
 *       the consumer to also check the fixed {@code payload_hash}, the target audience and the
 *       entitlement state; the signature only proves the envelope body was produced by a holder of
 *       the key.
 * </ul>
 */
public final class EventSignature {

    /**
     * Every member declared by contracts/event-envelope.schema.json, required and optional. {@code
     * additionalProperties: false} makes this list exhaustive: a new optional member must be added
     * here at the same time, or the signing bytes drift silently between the languages.
     */
    public static final List<String> ENVELOPE_KEYS = List.of(
            "event_id",
            "event_type",
            "schema_version",
            "aggregate_id",
            "aggregate_version",
            "merchant_id",
            "occurred_at",
            "producer",
            "traceparent",
            "causation_id",
            "payload",
            "signature",
            "signing_key_id");

    /** Signed members: everything except the signature itself. */
    public static final List<String> SIGNABLE_KEYS =
            ENVELOPE_KEYS.stream().filter(key -> !"signature".equals(key)).toList();

    private static final ObjectMapper MAPPER = new ObjectMapper();

    private EventSignature() {}

    /** Raised when an envelope cannot be signed or verified as specified. */
    public static class EventSignatureException extends IllegalArgumentException {

        private static final long serialVersionUID = 1L;

        public EventSignatureException(String message) {
            super(message);
        }

        public EventSignatureException(String message, Throwable cause) {
            super(message, cause);
        }
    }

    /** Return the canonical bytes covered by {@code signature}, per docs/contracts.md:17. */
    public static byte[] signingInputBytes(JsonNode envelope) {
        if (envelope == null || !envelope.isObject()) {
            throw new EventSignatureException("an envelope must be a JSON object");
        }
        var unsigned = MAPPER.createObjectNode();
        for (String key : SIGNABLE_KEYS) {
            JsonNode member = envelope.get(key);
            if (member == null) {
                // Absent and explicit null must sign the same bytes.
                unsigned.putNull(key);
            } else {
                unsigned.set(key, member);
            }
        }
        JsonNode payload = envelope.get("payload");
        if (payload == null || !payload.isObject()) {
            throw new EventSignatureException("envelope payload must be a JSON object to be signed");
        }
        return CanonicalJson.canonicalBytes(unsigned);
    }

    /** Return the base64 signature over the envelope's normalised signing input. */
    public static String sign(JsonNode envelope, PrivateKey privateKey) {
        try {
            Signature signer = Signature.getInstance("Ed25519");
            signer.initSign(privateKey);
            signer.update(signingInputBytes(envelope));
            return Base64.getEncoder().encodeToString(signer.sign());
        } catch (GeneralSecurityException error) {
            throw new EventSignatureException("Ed25519 signing failed", error);
        }
    }

    /** Raise {@link EventSignatureException} unless {@code signatureBase64} covers this envelope. */
    public static void verify(JsonNode envelope, String signatureBase64, PublicKey publicKey) {
        byte[] raw;
        try {
            raw = Base64.getDecoder().decode(signatureBase64);
        } catch (IllegalArgumentException error) {
            throw new EventSignatureException("signature is not valid base64", error);
        }
        if (raw.length != 64) {
            throw new EventSignatureException("Ed25519 signature must be 64 bytes, got " + raw.length);
        }
        try {
            Signature verifier = Signature.getInstance("Ed25519");
            verifier.initVerify(publicKey);
            verifier.update(signingInputBytes(envelope));
            if (!verifier.verify(raw)) {
                throw new EventSignatureException("envelope signature does not cover this envelope");
            }
        } catch (GeneralSecurityException error) {
            throw new EventSignatureException("Ed25519 verification failed", error);
        }
    }

    /**
     * Load the fixture signing key from its PKCS#8 DER encoding (RFC 8410).
     *
     * <p>The key in {@code expected-hashes.json} is derived from a public seed and exists only so the
     * frozen signature is verifiable in CI. Real keys are mounted at runtime and never committed
     * (docs/contracts.md:17).
     */
    public static PrivateKey privateKeyFromPkcs8(byte[] der) {
        try {
            return KeyFactory.getInstance("Ed25519").generatePrivate(new PKCS8EncodedKeySpec(der));
        } catch (GeneralSecurityException error) {
            throw new EventSignatureException("not a usable Ed25519 PKCS#8 key", error);
        }
    }

    /** Load the matching public key from its SubjectPublicKeyInfo DER encoding. */
    public static PublicKey publicKeyFromSpki(byte[] der) {
        try {
            return KeyFactory.getInstance("Ed25519").generatePublic(new X509EncodedKeySpec(der));
        } catch (GeneralSecurityException error) {
            throw new EventSignatureException("not a usable Ed25519 SubjectPublicKeyInfo key", error);
        }
    }
}
