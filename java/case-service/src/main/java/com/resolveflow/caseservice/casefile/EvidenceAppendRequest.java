package com.resolveflow.caseservice.casefile;

import com.fasterxml.jackson.annotation.JsonProperty;

/**
 * The append request, member for member with the contract's {@code EvidenceAppendRequest}.
 *
 * <p>There is no {@code revision} member, and its absence is the point: the revision material lands on
 * is the server's decision (current plus one), so a client has no way to write into a past revision
 * (docs/domain-model.md:27). A body that carries one is an unknown member and is refused as 400 rather
 * than being ignored.
 */
public record EvidenceAppendRequest(
        @JsonProperty("question_id") String questionId,
        @JsonProperty("text") String text,
        @JsonProperty("evidence_kind") String evidenceKind) {}
