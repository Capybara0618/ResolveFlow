package com.resolveflow.commerce.publicapi;

import com.resolveflow.commerce.catalog.ShoppingService;
import com.resolveflow.commerce.order.OrderLineReadService;
import com.resolveflow.commerce.publicapi.PublicOrderWire.*;
import com.resolveflow.shared.pagination.OrderReadCursor;
import com.resolveflow.shared.security.AuthenticatedPrincipal;
import com.resolveflow.shared.security.IdentityAccessWire.Context;
import com.resolveflow.shared.security.Role;
import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.Base64;
import java.util.Comparator;
import java.util.LinkedHashMap;
import org.springframework.stereotype.Service;
import tools.jackson.databind.ObjectMapper;

/** Bounded per-store reads followed by a global keyset merge. An outage fails the whole page. */
@Service
public class PublicOrderReads {
    private final OrderLineReadService commerce;
    private final ObjectMapper json = new ObjectMapper();

    public PublicOrderReads(OrderLineReadService commerce) {
        this.commerce = commerce;
    }

    public Page list(Context context, String cursor, Integer size) {
        var buyer = context.principal();
        if (!buyer.isPlatformBuyer()) return scoped(buyer, null, null, cursor, size);
        int limit = size == null ? 20 : size;
        if (limit < 1 || limit > 100) throw invalid();
        var bindings = context.bindings();
        // Personal demo has two controlled stores. This is an explicit bound, never a partial list.
        if (bindings.size() > 20)
            throw new ShoppingService.Refused(503, "UPSTREAM_UNAVAILABLE", "too many buyer stores");
        String bindingKey = bindings.stream()
                .map(s -> s.merchantId() + ":" + s.buyerId())
                .collect(java.util.stream.Collectors.joining("|"));
        var after = new LinkedHashMap<String, String>();
        if (cursor != null)
            try {
                if (cursor.isBlank() || cursor.length() > 16384) throw invalid();
                var node = json.readTree(new String(Base64.getUrlDecoder().decode(cursor), StandardCharsets.UTF_8));
                if (!buyer.buyerId().equals(node.path("buyer_id").asString())
                        || !bindingKey.equals(node.path("bindings").asString())) throw invalid();
                var anchors = node.get("after");
                if (anchors == null || !anchors.isObject()) throw invalid();
                for (var entry : anchors.properties()) {
                    if (bindings.stream().noneMatch(s -> s.merchantId().equals(entry.getKey()))
                            || !entry.getValue().isString()) throw invalid();
                    String encoded = entry.getValue().stringValue();
                    if (OrderReadCursor.decode(encoded) == null) throw invalid();
                    after.put(entry.getKey(), encoded);
                }
            } catch (RuntimeException error) {
                throw invalid();
            }
        var merged = new ArrayList<Summary>();
        boolean shardHasMore = false;
        for (var binding : bindings) {
            var page = scoped(binding.principal(buyer), null, null, after.get(binding.merchantId()), limit);
            shardHasMore |= page.page() != null && page.page().nextCursor() != null;
            for (var line : page.items()) merged.add(line.withMerchant(binding.merchantId(), binding.merchantName()));
        }
        // Stable sort preserves Commerce's line-id collation within each store. Java's String
        // comparison is not MySQL's utf8mb4 collation, so cross-store ties use merchant id instead.
        merged.sort(Comparator.comparing(Summary::paidAt).reversed().thenComparing(Summary::merchantId));
        var items = merged.stream().limit(limit).toList();
        String next = null;
        if (!items.isEmpty() && (merged.size() > limit || shardHasMore)) {
            for (var line : items)
                after.put(line.merchantId(), new OrderReadCursor(line.paidAt(), line.lineId()).encode());
            var node = json.createObjectNode();
            node.put("buyer_id", buyer.buyerId());
            node.put("bindings", bindingKey);
            var anchors = json.createObjectNode();
            after.forEach(anchors::put);
            node.set("after", anchors);
            next = Base64.getUrlEncoder()
                    .withoutPadding()
                    .encodeToString(node.toString().getBytes(StandardCharsets.UTF_8));
        }
        return new Page(items, new Meta(next, limit));
    }

    public Page read(Context context, String orderId) {
        var buyer = context.principal();
        if (!buyer.isPlatformBuyer()) {
            var page = scoped(buyer, orderId, null, null, null);
            if (page.items().isEmpty()) throw CommerceAccess.missing();
            return page;
        }
        for (var binding : context.bindings()) {
            var page = scoped(binding.principal(buyer), orderId, null, null, null);
            if (!page.items().isEmpty())
                return new Page(
                        page.items().stream()
                                .map(line -> line.withMerchant(binding.merchantId(), binding.merchantName()))
                                .toList(),
                        page.page());
        }
        throw CommerceAccess.missing();
    }

    private static ShoppingService.Refused invalid() {
        return new ShoppingService.Refused(400, "INVALID_ARGUMENT", "订单分页参数无效或不属于当前买家归属");
    }

    public Summary readLine(Context context, String lineId) {
        var buyer = context.principal();
        if (!buyer.isPlatformBuyer()) {
            var page = scoped(buyer, null, lineId, null, 1);
            if (page.items().size() != 1) throw CommerceAccess.missing();
            return page.items().getFirst();
        }
        for (var binding : context.bindings()) {
            var lines = scoped(binding.principal(buyer), null, lineId, null, 1).items();
            if (lines.size() == 1) return lines.getFirst().withMerchant(binding.merchantId(), binding.merchantName());
        }
        throw CommerceAccess.missing();
    }

    private Page scoped(AuthenticatedPrincipal principal, String order, String line, String cursor, Integer limit) {
        var page = commerce.list(
                principal.merchantId(),
                principal.role() == Role.CUSTOMER ? principal.buyerId() : null,
                order,
                line,
                cursor,
                limit);
        return new Page(page.items().stream().map(Summary::from).toList(), new Meta(page.nextCursor(), page.limit()));
    }
}
