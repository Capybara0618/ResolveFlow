package com.resolveflow.caseservice.casefile;

import com.fasterxml.jackson.annotation.JsonProperty;
import java.util.List;

/**
 * A person's proposal, member for member with the contract's {@code ManualProposalRequest}.
 *
 * <p>It is deliberately not a proposal document: there is no amount member (this service recomputes the money
 * from Commerce, which is what "Java owns the amount" means in practice), no run, and no reason codes — a
 * person does not classify the case. What the caller supplies is what the proposal relies on and why, and the
 * service builds the {@code ProposalView} document from it (C03.3c-1).
 *
 * <p>The members stay as the wire sent them and are parsed in the service, so a malformed submission is this
 * service's own 422 naming the member rather than a deserialisation failure the caller cannot act on.
 */
public record ManualProposalRequest(
        String action,
        @JsonProperty("evidence_refs") List<EvidenceCitation> evidenceRefs,
        @JsonProperty("policy_refs") List<PolicyCitation> policyRefs,
        String reason) {}
