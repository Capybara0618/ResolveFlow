package com.resolveflow.caseservice.casefile;

import com.resolveflow.caseservice.order.CommerceOrderLineClient;
import com.resolveflow.shared.security.AuthenticatedPrincipal;
import java.util.List;
import java.util.Optional;
import org.springframework.stereotype.Component;

/**
 * "Is this line mine?" — asked of Commerce, because Commerce owns the order data.
 *
 * <p>A narrow interface on purpose: opening a case needs one line's identity and nothing else, and
 * keeping the question this small is what keeps the scope honest. The scope is the principal's; it is
 * never an argument, so no caller can widen it by passing something.
 */
@Component
public class CommerceLineLookup {

    /** The one fact about a line that a case needs: which order it belongs to. */
    public record Line(String orderId, String lineId) {}

    private final CommerceOrderLineClient commerce;

    public CommerceLineLookup(CommerceOrderLineClient commerce) {
        this.commerce = commerce;
    }

    /**
     * The line if the principal may see it, empty otherwise.
     *
     * <p>Empty is not an error here: the caller decides that an invisible line is a 404, and the
     * distinction between "not yours" and "does not exist" is deliberately not made
     * (docs/core-contracts.md:27).
     */
    public Optional<Line> findLine(AuthenticatedPrincipal principal, String lineId) {
        List<CommerceOrderLineClient.OrderLineSummary> items =
                commerce.listByLine(principal, lineId).items();
        if (items == null || items.isEmpty()) {
            return Optional.empty();
        }
        CommerceOrderLineClient.OrderLineSummary line = items.get(0);
        return Optional.of(new Line(line.orderId(), line.lineId()));
    }
}
