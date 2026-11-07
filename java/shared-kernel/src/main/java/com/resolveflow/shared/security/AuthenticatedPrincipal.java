package com.resolveflow.shared.security;

/** Verified identity. A buyer may be scoped to a store for a domain operation. */
public record AuthenticatedPrincipal(String subject, String merchantId, Role role, String buyerId) {
    public boolean isPlatformBuyer() {
        return role == Role.CUSTOMER && buyerId != null && merchantId == null;
    }

    public AuthenticatedPrincipal {
        if (subject == null || subject.isBlank() || role == null) {
            throw new IllegalArgumentException("a principal needs a subject and role");
        }
        if (role == Role.CUSTOMER) {
            if (buyerId == null || buyerId.isBlank() || buyerId.length() > 64) {
                throw new IllegalArgumentException("a buyer needs a buyer_id");
            }
        } else if (buyerId != null) {
            throw new IllegalArgumentException("only a buyer carries buyer_id");
        }
        if (role == Role.PLATFORM_ADMIN && merchantId != null) {
            throw new IllegalArgumentException("a platform admin has no store scope");
        }
        if (role != Role.CUSTOMER && role != Role.PLATFORM_ADMIN && (merchantId == null || merchantId.isBlank())) {
            throw new IllegalArgumentException("merchant staff need merchant_id");
        }
        if (merchantId != null && (merchantId.isBlank() || merchantId.length() > 64)) {
            throw new IllegalArgumentException("invalid merchant_id");
        }
    }

    public static AuthenticatedPrincipal of(String subject, String merchantId, Role role, String buyerId) {
        return new AuthenticatedPrincipal(subject, merchantId, role, buyerId);
    }
}
