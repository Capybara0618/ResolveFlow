package com.resolveflow.shared.security;

/**
 * The authenticated caller, taken from the token and from nowhere else.
 *
 * <p>docs/core-contracts.md:15: "主体来自认证上下文；模型不得指定tenant/customer/run等身份" — the
 * principal is therefore a verified-token value, never a request field or a header. A gateway strips
 * {@code X-User}/{@code X-Role}/{@code X-Merchant}, and these types exist so a service never has to
 * read them: there is no way to build a principal from client input.
 *
 * <p>A legacy CUSTOMER has merchant/customer ids; a platform CUSTOMER has only buyerId.
 * Staff always have a merchant and neither customerId nor buyerId. Case resolves a platform buyer's
 * trusted resource binding before entering a merchant-scoped domain operation.
 */
public record AuthenticatedPrincipal(String subject, String merchantId, Role role, String customerId, String buyerId) {

    public AuthenticatedPrincipal(String subject, String merchantId, Role role, String customerId) {
        this(subject, merchantId, role, customerId, null);
    }

    public boolean isPlatformBuyer() {
        return buyerId != null;
    }

    public AuthenticatedPrincipal {
        if (subject == null || subject.isBlank()) {
            throw new IllegalArgumentException("a principal needs a subject");
        }
        if (role == null) {
            throw new IllegalArgumentException("a principal needs a role");
        }
        if (buyerId != null) {
            if (buyerId.isBlank()
                    || buyerId.length() > 64
                    || role != Role.CUSTOMER
                    || merchantId != null
                    || customerId != null) {
                throw new IllegalArgumentException("a platform buyer has only buyer_id and CUSTOMER role");
            }
        } else if (merchantId == null || merchantId.isBlank()) {
            throw new IllegalArgumentException("a principal needs a merchant_id");
        }
        if (buyerId == null && role.isCustomerScoped() && (customerId == null || customerId.isBlank())) {
            throw new IllegalArgumentException("a CUSTOMER principal must carry a customer_id");
        }
        if (!role.isCustomerScoped() && customerId != null) {
            throw new IllegalArgumentException("only a CUSTOMER principal carries a customer_id");
        }
    }

    public static AuthenticatedPrincipal of(String subject, String merchantId, Role role, String customerId) {
        return new AuthenticatedPrincipal(subject, merchantId, role, customerId);
    }
}
