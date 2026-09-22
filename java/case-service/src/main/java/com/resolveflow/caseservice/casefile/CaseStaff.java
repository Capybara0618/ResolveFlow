package com.resolveflow.caseservice.casefile;

import com.resolveflow.shared.security.AuthenticatedPrincipal;
import com.resolveflow.shared.security.Role;

/**
 * Who may act on a case as merchant staff.
 *
 * <p>The rule is one comparison, and it was written out in three places before this class existed (the review
 * queue, the human decision, and now the manual proposal). One rule in one place is the point; the refusal
 * sentence stays with each caller, because each act has its own reason and a shared sentence would explain
 * none of them (docs/core-contracts.md:33).
 *
 * <p>A customer-scoped token is the only refusal here. It is not that a customer is untrusted: the reviewer's
 * surfaces are the merchant's account of the case, and the customer is the party that account is about.
 */
final class CaseStaff {

    private CaseStaff() {}

    static boolean isStaff(AuthenticatedPrincipal principal) {
        return principal.role() != Role.CUSTOMER;
    }

    static void require(AuthenticatedPrincipal principal, String refusal) {
        if (!isStaff(principal)) {
            throw new CaseService.ForbiddenScopeException(refusal);
        }
    }
}
