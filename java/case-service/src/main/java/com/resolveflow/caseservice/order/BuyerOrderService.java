package com.resolveflow.caseservice.order;

import com.resolveflow.caseservice.auth.BuyerScopes;
import com.resolveflow.shared.pagination.OrderReadCursor;
import com.resolveflow.shared.security.AuthenticatedPrincipal;
import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.Base64;
import java.util.Comparator;
import java.util.LinkedHashMap;
import org.springframework.stereotype.Service;
import tools.jackson.databind.ObjectMapper;

/** Bounded per-store reads followed by a global keyset merge. An outage fails the whole page. */
@org.springframework.boot.autoconfigure.condition.ConditionalOnProperty(
        name = "resolveflow.compat.commerce-facade-enabled",
        havingValue = "true")
@Service
public class BuyerOrderService {
    private final BuyerScopes scopes;
    private final CommerceOrderLineClient commerce;
    private final ObjectMapper json = new ObjectMapper();

    public BuyerOrderService(BuyerScopes scopes, CommerceOrderLineClient commerce) {
        this.scopes = scopes;
        this.commerce = commerce;
    }

    public CommerceOrderLineClient.OrderLinePage list(AuthenticatedPrincipal buyer, String cursor, Integer size) {
        int limit = size == null ? 20 : size;
        if (limit < 1 || limit > 100) throw invalid();
        var bindings = scopes.list(buyer);
        // Personal demo has two controlled stores. This is an explicit bound, never a partial list.
        if (bindings.size() > 20) throw new CommerceOrderLineClient.CommerceProtocolException("too many buyer stores");
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
        var merged = new ArrayList<CommerceOrderLineClient.OrderLineSummary>();
        boolean shardHasMore = false;
        for (var binding : bindings) {
            var page = commerce.list(binding.principal(buyer), null, after.get(binding.merchantId()), limit);
            shardHasMore |= page.page() != null && page.page().nextCursor() != null;
            for (var line : page.items()) merged.add(line.withMerchant(binding.merchantId(), binding.merchantName()));
        }
        // Stable sort preserves Commerce's line-id collation within each store. Java's String
        // comparison is not MySQL's utf8mb4 collation, so cross-store ties use merchant id instead.
        merged.sort(Comparator.comparing(CommerceOrderLineClient.OrderLineSummary::paidAt)
                .reversed()
                .thenComparing(CommerceOrderLineClient.OrderLineSummary::merchantId));
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
        return new CommerceOrderLineClient.OrderLinePage(items, new CommerceOrderLineClient.PageMeta(next, limit));
    }

    public CommerceOrderLineClient.OrderLinePage read(AuthenticatedPrincipal buyer, String orderId) {
        for (var binding : scopes.list(buyer)) {
            var page = commerce.readOrder(binding.principal(buyer), orderId);
            if (!page.items().isEmpty())
                return new CommerceOrderLineClient.OrderLinePage(
                        page.items().stream()
                                .map(line -> line.withMerchant(binding.merchantId(), binding.merchantName()))
                                .toList(),
                        page.page());
        }
        throw new OrderController.OrderNotVisibleException();
    }

    private static CommerceOrderLineClient.CommerceRejectedQueryException invalid() {
        return new CommerceOrderLineClient.CommerceRejectedQueryException("订单分页参数无效或不属于当前买家归属");
    }

    public CommerceOrderLineClient.OrderLineSummary readLine(AuthenticatedPrincipal buyer, String lineId) {
        for (var binding : scopes.list(buyer)) {
            var lines = commerce.listByLine(binding.principal(buyer), lineId).items();
            if (lines.size() == 1) return lines.getFirst().withMerchant(binding.merchantId(), binding.merchantName());
        }
        throw new OrderController.OrderNotVisibleException();
    }
}
