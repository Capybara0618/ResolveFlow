package com.resolveflow.caseservice.auth;

import com.resolveflow.caseservice.casefile.CaseReadService;
import com.resolveflow.caseservice.casefile.CaseRepository;
import com.resolveflow.caseservice.order.CommerceOrderLineClient;
import com.resolveflow.shared.security.AuthenticatedPrincipal;
import com.resolveflow.shared.security.Role;
import java.util.List;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Service;

/** Trusted ownership lookup. Bindings cannot be created or claimed through a public endpoint. */
@Service
public class BuyerScopes {
    private final JdbcTemplate jdbc;
    private final CaseRepository cases;
    private final CommerceOrderLineClient commerce;

    public BuyerScopes(JdbcTemplate jdbc, CaseRepository cases, CommerceOrderLineClient commerce) {
        this.jdbc = jdbc;
        this.cases = cases;
        this.commerce = commerce;
    }

    public record Scope(String merchantId, String customerId, String merchantName) {
        public AuthenticatedPrincipal principal(AuthenticatedPrincipal buyer) {
            if (!buyer.isPlatformBuyer()) throw new IllegalArgumentException("platform buyer required");
            return new AuthenticatedPrincipal(buyer.subject(), merchantId, Role.CUSTOMER, customerId);
        }
    }

    public List<Scope> list(AuthenticatedPrincipal buyer) {
        if (!buyer.isPlatformBuyer()) throw new IllegalArgumentException("platform buyer required");
        return jdbc.query(
                """
            SELECT b.merchant_id,b.customer_id,m.display_name FROM buyer_customer_binding b
            JOIN identity_merchant m ON m.merchant_id=b.merchant_id
            WHERE b.buyer_id=? AND m.enabled=TRUE ORDER BY b.merchant_id
            """, (rs, n) -> new Scope(rs.getString(1), rs.getString(2), rs.getString(3)), buyer.buyerId());
    }

    public AuthenticatedPrincipal forCase(AuthenticatedPrincipal caller, String caseId) {
        if (!caller.isPlatformBuyer()) return caller;
        var row = cases.findCase(caseId);
        if (row != null)
            for (var scope : list(caller)) {
                if (row.merchantId().equals(scope.merchantId())
                        && row.customerId().equals(scope.customerId())) return scope.principal(caller);
            }
        throw new CaseReadService.CaseNotVisibleException();
    }

    public AuthenticatedPrincipal forLine(AuthenticatedPrincipal caller, String lineId) {
        if (!caller.isPlatformBuyer()) return caller;
        if (lineId == null || lineId.isBlank() || lineId.length() > 64)
            throw new com.resolveflow.caseservice.casefile.CaseService.SemanticInvalidException(
                    "line_id must contain 1-64 characters");
        // A scoped read for each trusted binding; no unscoped context read of arbitrary line ids.
        for (var scope : list(caller)) {
            var principal = scope.principal(caller);
            if (!commerce.listByLine(principal, lineId).items().isEmpty()) return principal;
        }
        throw new CaseReadService.CaseNotVisibleException();
    }
}
