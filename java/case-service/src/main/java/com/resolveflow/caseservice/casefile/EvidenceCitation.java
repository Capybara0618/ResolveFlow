package com.resolveflow.caseservice.casefile;

/**
 * An evidence citation as the run submitted it, member for member with the contract's {@code EvidenceRef}.
 *
 * <p><b>Recorded, not verified</b> (C03.2b-2). Verifying one means resolving a controlled {@code source_ref}
 * to an authoritative read and comparing the version and hash — the shipment and payment reads that arrive
 * with C04. Until then a proposal can be VALIDATED with its evidence references unverified, and the contract
 * says exactly that: {@code ProposalStatus.VALIDATED} claims the citations and the amount were re-checked,
 * not that every observation was. {@code source_ref} is still shape-checked (a URL is refused, not fetched),
 * because a reference that could be dereferenced is a different feature from a reference that is checked.
 */
public record EvidenceCitation(
        @com.fasterxml.jackson.annotation.JsonProperty("observation_id")
        String observationId,

        @com.fasterxml.jackson.annotation.JsonProperty("source_ref")
        String sourceRef,

        @com.fasterxml.jackson.annotation.JsonProperty("source_version")
        String sourceVersion,

        @com.fasterxml.jackson.annotation.JsonProperty("content_hash")
        String contentHash) {}
