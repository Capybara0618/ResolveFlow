package com.resolveflow.shared.security;

import com.fasterxml.jackson.annotation.JsonProperty;
import com.resolveflow.shared.shopping.ShippingWire;
import java.util.List;

/** Account authority protocol; it contains no orders, cases or client-supplied resource scopes. */
public final class IdentityAccessWire {
    private IdentityAccessWire() {}

    public record Resolve(String user_authorization, ShippingWire.Selection shipping) {
        @Override
        public String toString() {
            return "Resolve[redacted]";
        }
    }

    public record Binding(
            @JsonProperty("merchant_id") String merchantId,
            @JsonProperty("buyer_id") String buyerId,
            @JsonProperty("merchant_name") String merchantName) {
        public AuthenticatedPrincipal principal(AuthenticatedPrincipal buyer) {
            if (!buyer.isPlatformBuyer() || !buyer.buyerId().equals(buyerId))
                throw new IllegalArgumentException("scope must retain the authenticated buyer");
            return new AuthenticatedPrincipal(buyer.subject(), merchantId, Role.CUSTOMER, buyerId);
        }
    }

    public record Context(
            String subject,
            String merchant_id,
            Role role,
            String buyer_id,
            long identity_version,
            List<Binding> bindings,
            ShippingWire.Snapshot shipping) {
        public AuthenticatedPrincipal principal() {
            return new AuthenticatedPrincipal(subject, merchant_id, role, buyer_id);
        }
    }
}
