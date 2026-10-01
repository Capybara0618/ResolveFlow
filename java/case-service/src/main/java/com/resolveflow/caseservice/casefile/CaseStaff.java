package com.resolveflow.caseservice.casefile;

import com.resolveflow.shared.security.AuthenticatedPrincipal;
import com.resolveflow.shared.security.Role;

/** Merchant staff may read; human writes require a reviewer. Admin takeover arrives with collaboration. */
final class CaseStaff {

    private CaseStaff() {}

    static boolean isStaff(AuthenticatedPrincipal principal) {
        return principal.role().isMerchantStaff();
    }

    static boolean canReview(AuthenticatedPrincipal principal) {
        return principal.role() == Role.REVIEWER || principal.role() == Role.OPERATOR;
    }

    static void requireReviewer(AuthenticatedPrincipal principal, String refusal) {
        if (!canReview(principal)) throw new CaseService.ForbiddenScopeException(refusal);
    }

    static void require(AuthenticatedPrincipal principal, String refusal) {
        if (!isStaff(principal)) {
            throw new CaseService.ForbiddenScopeException(refusal);
        }
    }
}
