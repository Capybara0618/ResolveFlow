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

    /** What the order's ledger already accounts for; a test moves these to exhaust a line. */
    volatile long refundedAmount = 0;

    volatile long reservedRefundAmount = 0;

    /** When true, the context says the line belongs to someone else, which the re-check has to notice. */
    volatile boolean lineOwnerMismatch = false;

    StubCommerce(RestClient.Builder builder, JwtCodec codec) {
        super(builder, codec, "http://commerce.stub", "case-service");
    }

    /**
     * The state every test should start from.
     *
     * <p>One method rather than a line per test, because a knob a test sets and forgets is a failure in the
     * <em>next</em> test, which then reads as a bug in the re-check.
     */
    void reset() {
        paidAt = Instant.parse("2026-09-10T08:15:00Z");
        lineVisible = true;
        refundedAmount = 0;
        reservedRefundAmount = 0;
        lineOwnerMismatch = false;
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

    /**
     * The amount read the re-check recomputes from, with the ledger figures a test can move.
     *
     * <p>This is the half of Commerce that C03.2a added, and the proposal re-check is its first real
     * consumer; the real cross-service call is exercised by running both services (C03.2a's record).
     */
    @Override
    public java.util.Optional<LineContext> readLineContext(String lineId) {
        lastLineId = lineId;
        if (!lineVisible) {
            return java.util.Optional.empty();
        }
        return java.util.Optional.of(new LineContext(
                ORDER,
                lineId,
                lineOwnerMismatch ? "M-9999" : "M-1001",
                lineOwnerMismatch ? "C-9999" : "C-2002",
                "SKU-RED-M",
                "apparel",
                2,
                2599,
                refundedAmount,
                reservedRefundAmount,
                "CNY",
                paidAt,
                "PAID",
                3));
    }
}
