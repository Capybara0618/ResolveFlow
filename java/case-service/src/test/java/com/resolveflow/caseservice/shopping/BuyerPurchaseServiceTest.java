package com.resolveflow.caseservice.shopping;

import static org.assertj.core.api.Assertions.*;
import static org.mockito.ArgumentMatchers.*;
import static org.mockito.Mockito.*;

import com.resolveflow.caseservice.auth.BuyerScopes;
import com.resolveflow.shared.security.AuthenticatedPrincipal;
import com.resolveflow.shared.security.Role;
import com.resolveflow.shared.shopping.CheckoutWire.*;
import java.nio.charset.StandardCharsets;
import java.time.Instant;
import java.util.ArrayList;
import java.util.Base64;
import java.util.List;
import org.junit.jupiter.api.Test;

class BuyerPurchaseServiceTest {
    @Test
    void stableShardMergePreservesAnchorsAndBindsCursorToBuyerScopeAndFilters() {
        var buyer = new AuthenticatedPrincipal("buyer", null, Role.CUSTOMER, null, "B-one");
        var scopes = mock(BuyerScopes.class);
        var commerce = mock(CommerceShoppingClient.class);
        when(scopes.list(any()))
                .thenReturn(
                        List.of(new BuyerScopes.Scope("M-1", "C-1", "店一"), new BuyerScopes.Scope("M-2", "C-2", "店二")));
        var time = Instant.parse("2026-10-03T00:00:00.123456Z");
        when(commerce.purchases(anyString(), anyString(), nullable(String.class), nullable(String.class), anyInt()))
                .thenAnswer(inv -> {
                    String merchant = inv.getArgument(0), cursor = inv.getArgument(3);
                    int limit = inv.getArgument(4);
                    var ids = merchant.equals("M-1")
                            ? List.of(
                                    "draft:00000000-0000-4000-8000-000000000003",
                                    "order:00000000-0000-4000-8000-000000000002")
                            : List.of("draft:00000000-0000-4000-8000-000000000001");
                    int offset = cursor == null
                            ? 0
                            : ids.indexOf(new String(Base64.getUrlDecoder().decode(cursor), StandardCharsets.UTF_8)
                                            .split("\n")[1])
                                    + 1;
                    var rows = ids.stream()
                            .skip(offset)
                            .limit(limit)
                            .map(id -> new Purchase(
                                    id,
                                    null,
                                    merchant,
                                    merchant,
                                    "PAID",
                                    100,
                                    "CNY",
                                    time,
                                    null,
                                    time,
                                    "00000000-0000-4000-8000-000000000004",
                                    List.of(),
                                    null))
                            .toList();
                    return new Purchases(rows, offset + rows.size() < ids.size() ? "more" : null);
                });
        var service = new BuyerPurchaseService(scopes, commerce);
        var page = service.list(buyer, null, null, null, 1);
        var firstCursor = page.nextCursor();
        assertThatThrownBy(() -> service.list(
                        new AuthenticatedPrincipal("other", null, Role.CUSTOMER, null, "B-two"),
                        null,
                        null,
                        firstCursor,
                        1))
                .isInstanceOf(CommerceShoppingClient.Refused.class);
        assertThatThrownBy(() -> service.list(buyer, "M-1", null, firstCursor, 1))
                .isInstanceOf(CommerceShoppingClient.Refused.class);
        assertThatThrownBy(() -> service.list(buyer, null, "PAID", firstCursor, 1))
                .isInstanceOf(CommerceShoppingClient.Refused.class);
        var seen = new ArrayList<String>();
        String cursor = null;
        for (int i = 0; i < 4; i++) {
            var next = service.list(buyer, null, null, cursor, 1);
            seen.addAll(next.items().stream().map(Purchase::purchaseId).toList());
            cursor = next.nextCursor();
            if (cursor == null) break;
        }
        assertThat(seen)
                .containsExactly(
                        "draft:00000000-0000-4000-8000-000000000003",
                        "order:00000000-0000-4000-8000-000000000002",
                        "draft:00000000-0000-4000-8000-000000000001");
        assertThat(cursor).isNull();
        when(scopes.list(buyer)).thenReturn(List.of(new BuyerScopes.Scope("M-1", "different-customer", "店一")));
        assertThatThrownBy(() -> service.list(buyer, null, null, firstCursor, 1))
                .isInstanceOf(CommerceShoppingClient.Refused.class);
    }

    @Test
    void anyShardOutageFailsWholeList() {
        var buyer = new AuthenticatedPrincipal("buyer", null, Role.CUSTOMER, null, "B-one");
        var scopes = mock(BuyerScopes.class);
        var commerce = mock(CommerceShoppingClient.class);
        when(scopes.list(buyer))
                .thenReturn(
                        List.of(new BuyerScopes.Scope("M-1", "C-1", "店一"), new BuyerScopes.Scope("M-2", "C-2", "店二")));
        when(commerce.purchases(eq("M-1"), anyString(), any(), any(), anyInt()))
                .thenReturn(new Purchases(List.of(), null));
        when(commerce.purchases(eq("M-2"), anyString(), any(), any(), anyInt()))
                .thenThrow(new com.resolveflow.caseservice.order.CommerceOrderLineClient.CommerceUnavailableException(
                        "unavailable", null));
        assertThatThrownBy(() -> new BuyerPurchaseService(scopes, commerce).list(buyer, null, null, null, 24))
                .isInstanceOf(
                        com.resolveflow.caseservice.order.CommerceOrderLineClient.CommerceUnavailableException.class);
    }
}
