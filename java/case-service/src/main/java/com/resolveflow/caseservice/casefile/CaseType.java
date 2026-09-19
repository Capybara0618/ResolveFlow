package com.resolveflow.caseservice.casefile;

/**
 * How a case was investigated, member for member with the contract's {@code CaseType}
 * (contracts/core/openapi-case.yaml): the three fixed scenarios plus the explicit out-of-scope bucket.
 *
 * <p>This service does not decide the type — the run does, and the type is the first thing it has to state
 * (a run that cannot classify the case is exactly the {@code OUT_OF_SCOPE} answer). It is validated here so a
 * typo is a 422 the producer can read, rather than an unknown string stored where a reviewer reads it.
 */
public enum CaseType {
    LOGISTICS,
    DAMAGED,
    WRONG_MISSING,
    OUT_OF_SCOPE;

    public static CaseType of(String stated) {
        for (CaseType type : values()) {
            if (type.name().equals(stated)) {
                return type;
            }
        }
        throw new CaseService.SemanticInvalidException("unknown case_type: " + stated);
    }
}
