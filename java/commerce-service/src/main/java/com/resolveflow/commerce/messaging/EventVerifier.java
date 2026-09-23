package com.resolveflow.commerce.messaging;

import com.resolveflow.shared.core.CoreEnvelope;
import java.security.PublicKey;
import java.util.Map;
import tools.jackson.databind.JsonNode;

/**
 * Checking that a core event is one this service should act on.
 *
 * <p>Three questions, asked in this order because each makes the next one meaningful:
 *
 * <ol>
 *   <li><b>Is it shaped like a core event?</b> A message that is not an object, or that has no
 *       {@code signing_key_id}, cannot be checked at all and is refused rather than guessed at.
 *   <li><b>Is the signing key one I trust?</b> The key id travels inside the signed bytes, so trusting it is
 *       how origin is decided; a valid signature from an unknown key proves nothing about who sent it.
 *   <li><b>Does the signature cover this envelope, and is the event type the producer's own?</b>
 *       {@link CoreEnvelope#verify} answers both, so a result signed with case-service's key is refused even
 *       though the signature is genuine.
 * </ol>
 *
 * <p>What this deliberately does not do is decide what the event means. Verification answers "may I act on
 * this"; the business rules answer "should I", and merging the two is how an authorization check ends up
 * inside a signature helper.
 *
 * <p>Not a {@code @Component}: the trust list is configuration
 * ({@link EventTrustConfiguration}), so there is exactly one place that decides which keys are believed.
 */
public class EventVerifier {

    /** Why an event was refused, as a code the rejection log and an operator can both use. */
    public enum Refusal {
        MALFORMED("the message is not a core event envelope"),
        UNTRUSTED_KEY("the signing key is not one this service trusts"),
        BAD_SIGNATURE("the signature does not cover this envelope"),
        WRONG_DIRECTION("the event type does not belong to the producer that claims it");

        private final String description;

        Refusal(String description) {
            this.description = description;
        }

        public String description() {
            return description;
        }
    }

    /** Raised when a message is refused; carries the code the rejection row records. */
    public static class RefusedEventException extends RuntimeException {

        private static final long serialVersionUID = 1L;

        private final Refusal refusal;

        public RefusedEventException(Refusal refusal, String message) {
            super(message);
            this.refusal = refusal;
        }

        public Refusal refusal() {
            return refusal;
        }
    }

    private final Map<String, PublicKey> trustedKeys;

    public EventVerifier(Map<String, PublicKey> trustedKeys) {
        this.trustedKeys = Map.copyOf(trustedKeys);
    }

    /**
     * Verify one envelope, or raise.
     *
     * @return the same envelope, so a caller can use the verified document rather than the raw message
     */
    public JsonNode verify(JsonNode envelope) {
        if (envelope == null || !envelope.isObject()) {
            throw new RefusedEventException(Refusal.MALFORMED, "an event envelope is a JSON object");
        }
        JsonNode keyId = envelope.get("signing_key_id");
        if (keyId == null || !keyId.isString() || keyId.stringValue().isBlank()) {
            throw new RefusedEventException(Refusal.MALFORMED, "the envelope does not say which key signed it");
        }
        PublicKey key = trustedKeys.get(keyId.stringValue());
        if (key == null) {
            throw new RefusedEventException(
                    Refusal.UNTRUSTED_KEY, "key " + keyId.stringValue() + " is not in this service's trust list");
        }
        try {
            return CoreEnvelope.verify(envelope, key);
        } catch (CoreEnvelope.EnvelopeException envelopeProblem) {
            throw new RefusedEventException(direction(envelopeProblem), envelopeProblem.getMessage());
        } catch (IllegalArgumentException signatureProblem) {
            // CoreEventSignature.CoreSignatureException extends IllegalArgumentException, and it is what a
            // tampered document raises. Catching only the envelope type would let a bad signature escape as an
            // unhandled error, so it would never reach the rejection log — the one place an operator looks.
            throw new RefusedEventException(Refusal.BAD_SIGNATURE, signatureProblem.getMessage());
        }
    }

    /** A wrong direction and a broken signature are different problems; the log has to say which. */
    private static Refusal direction(CoreEnvelope.EnvelopeException problem) {
        String message = problem.getMessage() == null ? "" : problem.getMessage();
        boolean routing = message.contains("does not come from") || message.contains("belongs on");
        return routing ? Refusal.WRONG_DIRECTION : Refusal.BAD_SIGNATURE;
    }
}
