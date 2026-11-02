package com.resolveflow.commerce.publicapi;

import static org.assertj.core.api.Assertions.*;
import static org.mockito.ArgumentMatchers.*;
import static org.mockito.Mockito.*;

import com.resolveflow.commerce.catalog.ShoppingService;
import com.resolveflow.commerce.order.*;
import com.resolveflow.shared.pagination.OrderReadCursor;
import com.resolveflow.shared.security.IdentityAccessWire.*;
import com.resolveflow.shared.security.Role;
import java.time.Instant;
import java.util.*;
import org.junit.jupiter.api.Test;

class PublicOrderReadsTest {
    @Test
    void stableSameTimeMergeUsesNativeLineOrderAndRejectsChangedBindings() {
        var reads = mock(OrderLineReadService.class);
        var time = Instant.parse("2026-10-03T00:00:00.123456Z");
        var bindings = List.of(new Binding("M-1", "C-1", "one"), new Binding("M-2", "C-2", "two"));
        var context = new Context("buyer", null, Role.CUSTOMER, null, "B-1", 1, bindings, null);
        when(reads.list(anyString(), anyString(), isNull(), isNull(), nullable(String.class), anyInt()))
                .thenAnswer(inv -> {
                    String merchant = inv.getArgument(0), cursor = inv.getArgument(4);
                    int size = inv.getArgument(5);
                    var ids = merchant.equals("M-1") ? List.of("line-z", "line-A") : List.of("line-0");
                    int offset = cursor == null
                            ? 0
                            : ids.indexOf(OrderReadCursor.decode(cursor).lineId()) + 1;
                    var rows = ids.stream()
                            .skip(offset)
                            .limit(size)
                            .map(id -> new OrderLineRow(
                                    "order", id, "SKU", null, null, null, "category", 1, 100, "CNY", time, "PAID", 1))
                            .toList();
                    String next = offset + rows.size() < ids.size()
                            ? new OrderReadCursor(time, rows.getLast().lineId()).encode()
                            : null;
                    return new OrderLineReadService.Page(rows, next, size);
                });
        var service = new PublicOrderReads(reads);
        var first = service.list(context, null, 1);
        var changed = new Context(
                "buyer", null, Role.CUSTOMER, null, "B-1", 1, List.of(new Binding("M-1", "other", "one")), null);
        assertThatThrownBy(() -> service.list(changed, first.page().nextCursor(), 1))
                .isInstanceOf(ShoppingService.Refused.class);
        List<String> seen = new ArrayList<>();
        String cursor = null;
        do {
            var page = service.list(context, cursor, 1);
            seen.addAll(
                    page.items().stream().map(PublicOrderWire.Summary::lineId).toList());
            cursor = page.page().nextCursor();
        } while (cursor != null && seen.size() < 5);
        assertThat(seen).containsExactly("line-z", "line-A", "line-0");
        assertThat(cursor).isNull();
    }
}
