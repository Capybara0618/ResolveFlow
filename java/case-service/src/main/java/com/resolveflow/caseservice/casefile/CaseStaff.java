package com.resolveflow.caseservice.casefile;

import com.resolveflow.shared.security.AuthenticatedPrincipal;
import com.resolveflow.shared.security.Role;

/** Human writes additionally require a current owner permit; admin role alone grants no write access. */
final class CaseStaff {

    private CaseStaff() {}

    static boolean isStaff(AuthenticatedPrincipal principal) {
        return principal.role().isMerchantStaff();
    }

    static boolean canReview(AuthenticatedPrincipal principal) {
        return principal.role() == Role.REVIEWER
                || principal.role() == Role.OPERATOR
                || principal.role() == Role.MERCHANT_ADMIN;
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
