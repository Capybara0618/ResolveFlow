package com.resolveflow.commerce.publicapi;

import com.resolveflow.commerce.catalog.PurchaseReads;
import com.resolveflow.commerce.catalog.ShoppingService;
import com.resolveflow.shared.security.IdentityAccessWire.Context;
import com.resolveflow.shared.shopping.CheckoutWire.*;
import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.Base64;
import java.util.Comparator;
import java.util.LinkedHashMap;
import java.util.List;
import jdk.jfr.Category;
import jdk.jfr.Event;
import jdk.jfr.Label;
import jdk.jfr.Name;
import jdk.jfr.StackTrace;
import org.springframework.stereotype.Service;
import tools.jackson.databind.ObjectMapper;

/** Merge complete scoped shard pages; outages never masquerade as a partial personal list. */
@Service
public class BuyerPurchaseReads {
    private final PurchaseReads commerce;
    private final ObjectMapper json = new ObjectMapper();

    @Name("resolveflow.BuyerOrderShardRead")
    @Label("Buyer order shard read")
    @Category({"ResolveFlow", "Commerce"})
    @StackTrace(false)
    static final class ShardRead extends Event {
        @Label("Returned orders")
        int orders;

        @Label("Read completed")
        boolean completed;
    }

    public BuyerPurchaseReads(PurchaseReads commerce) {
        this.commerce = commerce;
    }

    private static ShoppingService.Refused invalid() {
        return new ShoppingService.Refused(400, "INVALID_ARGUMENT", "订单筛选或分页标识无效，或归属已变化");
    }

    public Purchases list(Context context, String store, String status, String cursor, Integer size) {
        var buyer = context.principal();
        int limit = size == null ? 24 : size;
        if (!buyer.isPlatformBuyer()
                || limit < 1
                || limit > 48
                || store != null && (store.isBlank() || store.length() > 64)
                || status != null
                        && !List.of(
                                        "WAITING_PAYMENT",
                                        "PAYMENT_PENDING",
                                        "PAID",
                                        "CANCELLED",
                                        "EXPIRED",
                                        "AWAITING_SHIPMENT",
                                        "AWAITING_RECEIPT",
                                        "COMPLETED",
                                        "AFTER_SALES",
                                        "LOGISTICS_UNKNOWN")
                                .contains(status)) throw invalid();
        var bindings = context.bindings();
        if (bindings.size() > 20)
            throw new ShoppingService.Refused(503, "UPSTREAM_UNAVAILABLE", "too many buyer stores");
        String bindingKey = bindings.stream()
                .map(s -> s.merchantId() + ":" + s.buyerId())
                .collect(java.util.stream.Collectors.joining("|"));
        String filter = (store == null ? "" : store) + "/" + (status == null ? "" : status);
        var after = new LinkedHashMap<String, String>();
        if (cursor != null)
            try {
                if (cursor.isBlank() || cursor.length() > 16384) throw invalid();
                var node = json.readTree(new String(Base64.getUrlDecoder().decode(cursor), StandardCharsets.UTF_8));
                if (!buyer.buyerId().equals(node.path("buyer_id").asString())
                        || !bindingKey.equals(node.path("bindings").asString())
                        || !filter.equals(node.path("filter").asString())) throw invalid();
                var anchors = node.get("after");
                if (anchors == null || !anchors.isObject()) throw invalid();
                for (var e : anchors.properties()) {
                    if (bindings.stream()
                                    .noneMatch(s -> s.merchantId().equals(e.getKey())
                                            && (store == null || store.equals(s.merchantId())))
                            || !e.getValue().isString()) throw invalid();
                    String value = e.getValue().stringValue();
                    validateAnchor(value);
                    after.put(e.getKey(), value);
                }
            } catch (RuntimeException e) {
                throw invalid();
            }
        var merged = new ArrayList<Purchase>();
        boolean shardHasMore = false;
        for (var binding : bindings) {
            if (store != null && !store.equals(binding.merchantId())) continue;
            var sample = new ShardRead();
            sample.begin();
            try {
                var page = commerce.list(
                        binding.merchantId(), binding.buyerId(), status, after.get(binding.merchantId()), limit);
                shardHasMore |= page.nextCursor() != null;
                merged.addAll(page.items());
                sample.orders = page.items().size();
                sample.completed = true;
            } finally {
                sample.end();
                sample.commit();
            }
        }
        // Each shard already has its native id ordering; stable ties preserve it.
        merged.sort(Comparator.comparing(Purchase::createdAt).reversed().thenComparing(Purchase::storeId));
        var items = merged.stream().limit(limit).toList();
        String next = null;
        if (!items.isEmpty() && (merged.size() > limit || shardHasMore)) {
            for (var item : items) after.put(item.storeId(), anchor(item));
            var node = json.createObjectNode();
            node.put("buyer_id", buyer.buyerId());
            node.put("bindings", bindingKey);
            node.put("filter", filter);
            var anchors = json.createObjectNode();
            after.forEach(anchors::put);
            node.set("after", anchors);
            next = Base64.getUrlEncoder()
                    .withoutPadding()
                    .encodeToString(node.toString().getBytes(StandardCharsets.UTF_8));
        }
        return new Purchases(items, next);
    }

    private static String anchor(Purchase p) {
        return Base64.getUrlEncoder()
                .withoutPadding()
                .encodeToString((p.createdAt() + "\n" + p.purchaseId()).getBytes(StandardCharsets.UTF_8));
    }

    private static void validateAnchor(String value) {
        if (value.isBlank() || value.length() > 256) throw invalid();
        var fields = new String(Base64.getUrlDecoder().decode(value), StandardCharsets.UTF_8).split("\n", -1);
        if (fields.length != 2 || !fields[1].matches("(draft|order):[0-9a-fA-F-]{36}")) throw invalid();
        java.time.Instant.parse(fields[0]);
    }
}
