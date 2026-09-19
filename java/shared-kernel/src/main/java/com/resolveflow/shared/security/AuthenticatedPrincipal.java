package com.resolveflow.shared.security;

/**
 * The authenticated caller, taken from the token and from nowhere else.
 *
 * <p>docs/core-contracts.md:15: "主体来自认证上下文；模型不得指定tenant/customer/run等身份" — the
 * principal is therefore a verified-token value, never a request field or a header. A gateway strips
 * {@code X-User}/{@code X-Role}/{@code X-Merchant}, and these types exist so a service never has to
 * read them: there is no way to build a principal from client input.
 *
 * <p>{@code customerId} is present exactly when the role is customer-scoped, so a merchant-scoped
 * caller cannot pretend to be a specific customer (and vice versa).
 */
public record AuthenticatedPrincipal(String subject, String merchantId, Role role, String customerId) {

    public AuthenticatedPrincipal {
        if (subject == null || subject.isBlank()) {
            throw new IllegalArgumentException("a principal needs a subject");
        }
        if (merchantId == null || merchantId.isBlank()) {
            throw new IllegalArgumentException("a principal needs a merchant_id");
        }
        if (role == null) {
            throw new IllegalArgumentException("a principal needs a role");
        }
        if (role.isCustomerScoped() && (customerId == null || customerId.isBlank())) {
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
