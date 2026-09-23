package com.resolveflow.caseservice.result;

import com.resolveflow.shared.core.CoreEnvelope;
import java.security.PublicKey;
import java.util.Map;
import tools.jackson.databind.JsonNode;

/**
 * Checking that a refund result is one this service should act on.
 *
 * <p>The mirror of Commerce's {@code EventVerifier} (C05.1b), because the problem is the same one in the other
 * direction and the refusals have to mean the same things. Three questions, asked in this order because each
 * makes the next one meaningful:
 *
 * <ol>
 *   <li><b>Is it shaped like a core event?</b> A message that is not an object, or that has no
 *       {@code signing_key_id}, cannot be checked at all and is refused rather than guessed at.
 *   <li><b>Is the signing key one I trust?</b> The key id travels inside the signed bytes, so trusting it is
 *       how origin is decided; a valid signature from an unknown key proves nothing about who sent it.
 *   <li><b>Does the signature cover this envelope, and is the event type the producer's own?</b>
 *       {@link CoreEnvelope#verify} answers both, so a result signed with case-service's own key is refused —
 *       by the trust list first, and by the producer rule if the key were somehow trusted.
 * </ol>
 *
 * <p>What this deliberately does not do is decide what the result <em>means for a case</em>. Verification
 * answers "may I act on this"; whether the merchant and the line match the case is a statement about this
 * service's own records, and it stays in {@link CaseResultConsumer} where those records are read.
 *
 * <p>Not a {@code @Component}: the trust list is configuration ({@link CaseResultTrustConfiguration}), so there
 * is exactly one place that decides which keys are believed.
 */
public class CaseResultVerifier {

    /** Why a result was refused, as a code the rejection log and an operator can both use. */
    public enum Refusal {
        MALFORMED("the message is not a core event envelope"),
        UNTRUSTED_KEY("the signing key is not one this service trusts"),
        BAD_SIGNATURE("the signature does not cover this envelope"),
        WRONG_DIRECTION("the event type does not belong to the producer that claims it"),
        UNKNOWN_OPERATION("the result names an operation this service never issued a command for"),
        WRONG_MERCHANT("the result is scoped to a merchant that does not own the case"),
        LINE_MISMATCH("the result names a line the case does not cover"),
        AMOUNT_MISMATCH("the result reports money this case never authorised");

        private final String description;

        Refusal(String description) {
            this.description = description;
        }

        public String description() {
            return description;
        }
    }

    /** Raised when a result is refused; carries the code the rejection row records. */
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

    public CaseResultVerifier(Map<String, PublicKey> trustedKeys) {
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
            throw new RefusedEventException(refusalFor(envelopeProblem.reason()), envelopeProblem.getMessage());
        } catch (IllegalArgumentException signatureProblem) {
            // CoreEventSignature.CoreSignatureException extends IllegalArgumentException, and it is what a
            // tampered document raises. Catching only the envelope type would let a bad signature escape as an
            // unhandled error, so it would never reach the rejection log — the one place an operator looks.
            throw new RefusedEventException(Refusal.BAD_SIGNATURE, signatureProblem.getMessage());
        }
    }

    /**
     * This service's name for the shared kernel's reason.
     *
     * <p>A switch rather than a text match on purpose (C05.3d): the previous version decided by looking for
     * phrases in the exception's message, which made the refusal code depend on another module's wording — and
     * it defaulted everything unrecognised to {@code BAD_SIGNATURE}, so a wrong {@code schema_version} was
     * filed as a tampered document. Both services make the same mapping, and the compiler now asks both of them
     * for an answer whenever a reason is added.
     */
    private static Refusal refusalFor(CoreEnvelope.EnvelopeException.Reason reason) {
        return switch (reason) {
            case WRONG_ROUTE -> Refusal.WRONG_DIRECTION;
            case MALFORMED -> Refusal.MALFORMED;
        };
    }
}
