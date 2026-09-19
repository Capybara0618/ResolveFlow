package com.resolveflow.caseservice.casefile;

import com.resolveflow.caseservice.order.CommerceOrderLineClient;
import com.resolveflow.shared.security.AuthenticatedPrincipal;
import com.resolveflow.shared.security.JwtCodec;
import java.time.Instant;
import java.util.List;
import org.springframework.web.client.RestClient;

/**
 * A Commerce that answers one question: is the line visible to this principal?
 *
 * <p>The case tests are about Case's half of the contract — the slot, the idempotent answer, the
 * transaction — so Commerce is stubbed here and the real cross-service call is exercised by running
 * both services (see the C02.1 record). The stub records the scope it was handed, which is how a test
 * can tell that the scope came from the token rather than from the request body.
 */
class StubCommerce extends CommerceOrderLineClient {

    static final String ORDER = "00000000-0000-4000-8000-0000000000aa";

    /** The payment time Commerce reports; a test moves it to ask for a different policy version. */
    volatile Instant paidAt = Instant.parse("2026-09-10T08:15:00Z");

    volatile boolean lineVisible = true;
    volatile AuthenticatedPrincipal lastPrincipal;
    volatile String lastLineId;

    StubCommerce(RestClient.Builder builder, JwtCodec codec) {
        super(builder, codec, "http://commerce.stub", "case-service");
    }

    @Override
    public OrderLinePage listByLine(AuthenticatedPrincipal principal, String lineId) {
        lastPrincipal = principal;
        lastLineId = lineId;
        if (!lineVisible) {
            return new OrderLinePage(List.of(), new PageMeta(null, 1));
        }
        return new OrderLinePage(
                List.of(new OrderLineSummary(ORDER, lineId, "SKU-RED-M", "apparel", 2, 2599, "CNY", paidAt, "PAID", 3)),
                new PageMeta(null, 1));
    }
}
