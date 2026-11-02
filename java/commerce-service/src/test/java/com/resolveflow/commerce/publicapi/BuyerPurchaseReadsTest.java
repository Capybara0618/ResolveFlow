package com.resolveflow.commerce.publicapi;

import static org.assertj.core.api.Assertions.*;
import static org.mockito.ArgumentMatchers.*;
import static org.mockito.Mockito.*;

import com.resolveflow.commerce.catalog.*;
import com.resolveflow.shared.security.IdentityAccessWire.*;
import com.resolveflow.shared.security.Role;
import com.resolveflow.shared.shopping.CheckoutWire.*;
import java.time.Instant;
import java.util.*;
import org.junit.jupiter.api.Test;

class BuyerPurchaseReadsTest {
    Context actor(String buyer, List<Binding> bindings) {
        return new Context(buyer, null, Role.CUSTOMER, null, buyer, 1, bindings, null);
    }

    @Test
    void tiedTimesPreserveNativeStoreOrderAndCursorBindsBuyerBindingsAndFilters() {
        var reads = mock(PurchaseReads.class);
        var bindings = List.of(new Binding("M-1", "C-1", "one"), new Binding("M-2", "C-2", "two"));
        var owner = actor("buyer", bindings);
        var time = Instant.parse("2026-10-03T00:00:00.123456Z");
        when(reads.list(anyString(), anyString(), nullable(String.class), nullable(String.class), anyInt()))
                .thenAnswer(inv -> {
                    String merchant = inv.getArgument(0), cursor = inv.getArgument(3);
                    int limit = inv.getArgument(4);
                    var ids = merchant.equals("M-1")
                            ? List.of(
                                    "draft:00000000-0000-4000-8000-000000000003",
                                    "order:00000000-0000-4000-8000-000000000002")
                            : List.of("draft:00000000-0000-4000-8000-000000000001");
                    int offset = cursor == null ? 0 : ids.indexOf(PurchaseReads.anchor(cursor)[1]) + 1;
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
        var service = new BuyerPurchaseReads(reads);
        var first = service.list(owner, null, null, null, 1);
        for (var other :
                List.of(actor("other", bindings), actor("buyer", List.of(new Binding("M-1", "different", "one")))))
            assertThatThrownBy(() -> service.list(other, null, null, first.nextCursor(), 1))
                    .isInstanceOf(ShoppingService.Refused.class);
        assertThatThrownBy(() -> service.list(owner, "M-1", null, first.nextCursor(), 1))
                .isInstanceOf(ShoppingService.Refused.class);
        assertThatThrownBy(() -> service.list(owner, null, "PAID", first.nextCursor(), 1))
                .isInstanceOf(ShoppingService.Refused.class);
        List<String> seen = new ArrayList<>();
        String cursor = null;
        do {
            var page = service.list(owner, null, null, cursor, 1);
            seen.addAll(page.items().stream().map(Purchase::purchaseId).toList());
            cursor = page.nextCursor();
        } while (cursor != null && seen.size() < 5);
        assertThat(seen)
                .containsExactly(
                        "draft:00000000-0000-4000-8000-000000000003",
                        "order:00000000-0000-4000-8000-000000000002",
                        "draft:00000000-0000-4000-8000-000000000001");
        assertThat(cursor).isNull();
    }

    @Test
    void unavailableStoreCannotBecomeAnEmptyOrPartialPersonalList() {
        var reads = mock(PurchaseReads.class);
        when(reads.list(eq("M-1"), anyString(), isNull(), isNull(), anyInt()))
                .thenReturn(new Purchases(List.of(), null));
        when(reads.list(eq("M-2"), anyString(), isNull(), isNull(), anyInt()))
                .thenThrow(new ShoppingService.Refused(503, "UPSTREAM_UNAVAILABLE", "store unavailable"));
        var owner = actor("buyer", List.of(new Binding("M-1", "C-1", "one"), new Binding("M-2", "C-2", "two")));
        assertThatThrownBy(() -> new BuyerPurchaseReads(reads).list(owner, null, null, null, 20))
                .isInstanceOfSatisfying(
                        ShoppingService.Refused.class, e -> assertThat(e.status).isEqualTo(503));
    }
}
