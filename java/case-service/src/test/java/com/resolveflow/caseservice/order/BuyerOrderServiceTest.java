package com.resolveflow.caseservice.order;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyInt;
import static org.mockito.ArgumentMatchers.isNull;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.when;

import com.resolveflow.caseservice.auth.BuyerScopes;
import com.resolveflow.shared.pagination.OrderReadCursor;
import com.resolveflow.shared.security.AuthenticatedPrincipal;
import com.resolveflow.shared.security.Role;
import java.time.Instant;
import java.util.ArrayList;
import java.util.List;
import org.junit.jupiter.api.Test;

class BuyerOrderServiceTest {
    @Test
    void tiedTimesKeepEachStoresDatabaseOrderAndUnconsumedStoreAnchors() {
        var buyer = new AuthenticatedPrincipal("buyer", null, Role.CUSTOMER, null, "B-one");
        var scopes = mock(BuyerScopes.class);
        var commerce = mock(CommerceOrderLineClient.class);
        when(scopes.list(buyer))
                .thenReturn(
                        List.of(new BuyerScopes.Scope("M-1", "C-1", "店一"), new BuyerScopes.Scope("M-2", "C-2", "店二")));
        var time = Instant.parse("2026-10-03T00:00:00.123456Z");
        when(commerce.list(any(), isNull(), org.mockito.ArgumentMatchers.nullable(String.class), anyInt()))
                .thenAnswer(invocation -> {
                    AuthenticatedPrincipal p = invocation.getArgument(0);
                    String encoded = invocation.getArgument(2);
                    var anchor = OrderReadCursor.decode(encoded);
                    // The database supplies the order; Case must not re-sort same-store ties by Java strings.
                    List<String> ids = p.merchantId().equals("M-1") ? List.of("a", "B") : List.of("m");
                    int offset = anchor == null ? 0 : ids.indexOf(anchor.lineId()) + 1;
                    int limit = invocation.getArgument(3);
                    var rows = ids.stream()
                            .skip(offset)
                            .limit(limit)
                            .map(id -> new CommerceOrderLineClient.OrderLineSummary(
                                    "00000000-0000-4000-8000-000000000001",
                                    id,
                                    "SKU",
                                    null,
                                    null,
                                    "home",
                                    1,
                                    100,
                                    "CNY",
                                    time,
                                    "PAID",
                                    1))
                            .toList();
                    String next = offset + rows.size() < ids.size()
                            ? new OrderReadCursor(time, rows.getLast().lineId()).encode()
                            : null;
                    return new CommerceOrderLineClient.OrderLinePage(
                            rows, new CommerceOrderLineClient.PageMeta(next, limit));
                });
        var service = new BuyerOrderService(scopes, commerce);
        String cursor = null;
        var seen = new ArrayList<String>();
        for (int guard = 0; guard < 4; guard++) {
            var page = service.list(buyer, cursor, 1);
            seen.addAll(page.items().stream()
                    .map(CommerceOrderLineClient.OrderLineSummary::lineId)
                    .toList());
            cursor = page.page().nextCursor();
            if (cursor == null) break;
        }
        assertThat(seen).containsExactly("a", "B", "m");
        assertThat(cursor).isNull();
    }
}
