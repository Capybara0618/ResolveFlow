package com.resolveflow.caseservice.casefile;

import com.fasterxml.jackson.annotation.JsonProperty;

/** The cancel request, member for member with the contract's {@code ReasonRequest}. */
public record ReasonRequest(@JsonProperty("reason") String reason) {}
