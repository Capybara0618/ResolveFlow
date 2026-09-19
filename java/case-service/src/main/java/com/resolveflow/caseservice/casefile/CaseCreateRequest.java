package com.resolveflow.caseservice.casefile;

import com.fasterxml.jackson.annotation.JsonProperty;
import java.util.List;

/**
 * The create request, member for member with the core contract's {@code CaseCreateRequest}.
 *
 * <p>It is a plain carrier with no validation annotations on purpose: the two kinds of refusal are
 * different answers. A malformed body — an unknown member, a number where a string belongs — is
 * refused by the reader as 400. A well-formed body that asks for something core cannot do is 422, and
 * that decision belongs in the service, where it can explain itself, rather than in a bean-validation
 * annotation whose failure mode is whatever the framework defaults to.
 */
public record CaseCreateRequest(
        @JsonProperty("line_id") String lineId,
        @JsonProperty("description") String description,
        @JsonProperty("requested_actions") List<String> requestedActions) {}
