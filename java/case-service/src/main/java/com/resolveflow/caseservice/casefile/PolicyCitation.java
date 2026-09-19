package com.resolveflow.caseservice.casefile;

/**
 * A policy citation as the run submitted it, member for member with the contract's {@code PolicyRef}.
 *
 * <p>Every member is checked against this service's own store — the version pinned on the case, then the
 * bundle's version, the rule, its chunk and its content hash — so a citation that reaches approval names
 * rules this service can still read, rather than rules the run says it read.
 */
public record PolicyCitation(
        @com.fasterxml.jackson.annotation.JsonProperty("bundle_id")
        String bundleId,

        String version,

        @com.fasterxml.jackson.annotation.JsonProperty("rule_id")
        String ruleId,

        @com.fasterxml.jackson.annotation.JsonProperty("chunk_id")
        String chunkId,

        @com.fasterxml.jackson.annotation.JsonProperty("content_hash")
        String contentHash) {}
