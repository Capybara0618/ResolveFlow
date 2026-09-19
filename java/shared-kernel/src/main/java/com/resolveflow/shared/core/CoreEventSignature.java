package com.resolveflow.shared.core;

import com.resolveflow.shared.contract.CanonicalJson;
import java.security.GeneralSecurityException;
import java.security.PrivateKey;
import java.security.PublicKey;
import java.security.Signature;
import java.util.Base64;
import java.util.List;
import tools.jackson.databind.JsonNode;
import tools.jackson.databind.ObjectMapper;

/**
 * The core event signature: what a core envelope signs, and how to sign or verify it.
 *
 * <p>The compat signer ({@code com.resolveflow.shared.contract.EventSignature}) signs a different
 * byte sequence: it injects {@code aggregate_id}/{@code aggregate_version} (absent from a core
 * envelope, which keeps the version inside the result payload — docs/domain-model.md:3) and it omits
 * {@code topic} (which a core envelope must sign — docs/core-contracts.md:19). Reusing it would give
 * two implementations that are each self-consistent and cannot verify each other, so core gets its
 * own normalisation and a test asserting the two inputs differ.
 *
 * <p>Absent and explicit null sign the same bytes, as in the compat signer: a producer that omits an
 * optional member and one that sends {@code null} describe the same envelope.
 */
public final class CoreEventSignature {

    /** The signed members, per docs/core-contracts.md:19 — everything except the signature itself. */
    public static final List<String> SIGNABLE_KEYS = List.of(
            "event_id",
            "event_type",
            "schema_version",
            "merchant_id",
            "occurred_at",
            "producer",
            "topic",
            "traceparent",
            "causation_id",
            "payload",
            "signing_key_id");

    private static final ObjectMapper MAPPER = new ObjectMapper();

    private CoreEventSignature() {}

    /** Raised when a core envelope cannot be signed or verified as specified. */
    public static class CoreSignatureException extends IllegalArgumentException {

        private static final long serialVersionUID = 1L;

        public CoreSignatureException(String message) {
            super(message);
        }

        public CoreSignatureException(String message, Throwable cause) {
            super(message, cause);
        }
    }

    /** The canonical bytes a core signature covers (docs/core-contracts.md:19). */
    public static byte[] signingInputBytes(JsonNode envelope) {
        if (envelope == null || !envelope.isObject()) {
            throw new CoreSignatureException("a core envelope must be a JSON object");
        }
        JsonNode payload = envelope.get("payload");
        if (payload == null || !payload.isObject()) {
            throw new CoreSignatureException("core envelope payload must be a JSON object to be signed");
        }
        var unsigned = MAPPER.createObjectNode();
        for (String key : SIGNABLE_KEYS) {
            JsonNode member = envelope.get(key);
            if (member == null) {
                unsigned.putNull(key);
            } else {
                unsigned.set(key, member);
            }
        }
        return CanonicalJson.canonicalBytes(unsigned);
    }

    /** The base64 signature over a core envelope's normalised signing input. */
    public static String sign(JsonNode envelope, PrivateKey privateKey) {
        try {
            Signature signer = Signature.getInstance("Ed25519");
            signer.initSign(privateKey);
            signer.update(signingInputBytes(envelope));
            return Base64.getEncoder().encodeToString(signer.sign());
        } catch (GeneralSecurityException error) {
            throw new CoreSignatureException("Ed25519 signing failed", error);
        }
    }

    /** Raise {@link CoreSignatureException} unless {@code signatureBase64} covers this envelope. */
    public static void verify(JsonNode envelope, String signatureBase64, PublicKey publicKey) {
        byte[] raw;
        try {
            raw = Base64.getDecoder().decode(signatureBase64);
        } catch (IllegalArgumentException error) {
            throw new CoreSignatureException("core signature is not valid base64", error);
        }
        if (raw.length != 64) {
            throw new CoreSignatureException("Ed25519 signature must be 64 bytes, got " + raw.length);
        }
        try {
            Signature verifier = Signature.getInstance("Ed25519");
            verifier.initVerify(publicKey);
            verifier.update(signingInputBytes(envelope));
            if (!verifier.verify(raw)) {
                throw new CoreSignatureException("core envelope signature does not cover this envelope");
            }
        } catch (GeneralSecurityException error) {
            throw new CoreSignatureException("Ed25519 verification failed", error);
        }
    }
}
