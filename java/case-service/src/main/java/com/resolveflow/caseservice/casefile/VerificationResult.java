package com.resolveflow.caseservice.casefile;

/**
 * What a person concluded about one record (contracts/core/openapi-case.yaml, {@code VerificationResult}).
 *
 * <p>Three answers, not two: {@code INCONCLUSIVE} exists so that a reviewer who cannot establish the record
 * does not have to pick a side it does not hold. Recorded as a structured member rather than as a sentence,
 * because the case view and any later re-check read this value; a conclusion that has to be parsed out of
 * prose is not a fact a program can rely on.
 */
public enum VerificationResult {
    CONFIRMED,
    REFUTED,
    INCONCLUSIVE;

    /** The contract's spelling, refusing an unknown value instead of mapping it to a default. */
    public static VerificationResult of(String raw) {
        if (raw == null || raw.isBlank()) {
            throw new IllegalArgumentException("verification_result is required");
        }
        for (VerificationResult candidate : values()) {
            if (candidate.name().equals(raw)) {
                return candidate;
            }
        }
        throw new IllegalArgumentException(
                "verification_result must be one of CONFIRMED, REFUTED, INCONCLUSIVE, not " + raw);
    }

    /** True when the reviewer concluded the record does not hold, which is the case that can revoke. */
    public boolean refutes() {
        return this == REFUTED;
    }
}
