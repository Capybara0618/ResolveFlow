package com.resolveflow.shared.security;

import com.fasterxml.jackson.annotation.JsonProperty;
import com.resolveflow.shared.shopping.ShippingWire;
import java.util.List;

/** Account authority protocol; it contains no orders, cases or client-supplied resource scopes. */
public final class IdentityAccessWire {
    private IdentityAccessWire() {}

    public record Resolve(String user_authorization, ShippingWire.Selection shipping) {}

    public record Binding(
            @JsonProperty("merchant_id") String merchantId,
            @JsonProperty("customer_id") String customerId,
            @JsonProperty("merchant_name") String merchantName) {
        public AuthenticatedPrincipal principal(AuthenticatedPrincipal buyer) {
            if (!buyer.isPlatformBuyer()) throw new IllegalArgumentException("platform buyer required");
            return new AuthenticatedPrincipal(buyer.subject(), merchantId, Role.CUSTOMER, customerId);
        }
    }

    public record Context(
            String subject,
            String merchant_id,
            Role role,
            String customer_id,
            String buyer_id,
            long identity_version,
            List<Binding> bindings,
            ShippingWire.Snapshot shipping) {
        public AuthenticatedPrincipal principal() {
            return new AuthenticatedPrincipal(subject, merchant_id, role, customer_id, buyer_id);
        }
    }
}
