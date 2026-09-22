package com.resolveflow.caseservice.casefile;

/**
 * Who wrote a proposal, member for member with the contract's {@code ProposalOrigin}.
 *
 * <p>It is an enum rather than a nullable run id because the two authors produce genuinely different
 * documents (contracts/core/openapi-case.yaml {@code ProposalView}): a run classified the case and named
 * reason codes, a person did neither, and the difference has to be readable rather than inferred from which
 * members happen to be missing.
 */
public enum ProposalOrigin {
    AGENT,
    HUMAN;

    public static ProposalOrigin of(String stored) {
        try {
            return valueOf(stored);
        } catch (IllegalArgumentException error) {
            throw new IllegalStateException("the database holds an unknown proposal origin: " + stored, error);
        }
    }
}
