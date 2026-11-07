package com.resolveflow.commerce.catalog;

import com.resolveflow.shared.shopping.CheckoutWire.Purchase;
import com.resolveflow.shared.shopping.MultiCheckoutWire.*;
import com.resolveflow.shared.shopping.ShoppingWire.DraftRequest;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.sql.Timestamp;
import java.time.Clock;
import java.time.Instant;
import java.time.temporal.ChronoUnit;
import java.util.Comparator;
import java.util.HexFormat;
import java.util.List;
import java.util.UUID;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Isolation;
import org.springframework.transaction.annotation.Transactional;

@Service
public class MultiCheckoutService {
    private final JdbcTemplate jdbc;
    private final CartService cart;
    private final ShoppingService shop;
    private final PurchaseReads reads;
    private final Clock clock;

    public MultiCheckoutService(
            JdbcTemplate jdbc, CartService cart, ShoppingService shop, PurchaseReads reads, Clock clock) {
        this.jdbc = jdbc;
        this.cart = cart;
        this.shop = shop;
        this.reads = reads;
        this.clock = clock;
    }

    private static void revision(Long r) {
        if (r == null || r < 0 || r >= 9007199254740991L) throw new IllegalArgumentException("购物车版本无效");
    }

    private static List<String> skus(List<String> ids) {
        if (ids == null
                || ids.isEmpty()
                || ids.size() > 20
                || ids.stream().anyMatch(s -> s == null || !s.matches("[A-Za-z0-9_-]{1,64}"))
                || ids.stream().distinct().count() != ids.size()) throw new IllegalArgumentException("请选择1到20种不同规格");
        return ids.stream().sorted().toList();
    }

    private static ShoppingService.Refused changed(String code, String message) {
        return new ShoppingService.Refused(409, code, message);
    }

    @Transactional(readOnly = true)
    public Quote quote(QuoteCommand c) {
        if (c == null || c.request() == null) throw new IllegalArgumentException("报价请求无效");
        revision(c.request().expectedRevision());
        var ids = skus(c.request().skuIds());
        var g = cart.read(c.merchantId(), c.buyerId());
        if (g.revision() != c.request().expectedRevision()) throw changed("CART_CHANGED", "购物车已更新，请重新读取");
        var lines = ids.stream()
                .map(id -> {
                    var item = g.items().stream()
                            .filter(i -> i.skuId().equals(id))
                            .findFirst()
                            .orElseThrow(() -> changed("CART_CHANGED", "所选商品已不在购物车，请重新读取"));
                    var q = shop.quote(
                            new com.resolveflow.shared.shopping.ShoppingWire.QuoteRequest(id, item.quantity()));
                    if (!q.product().storeId().equals(c.merchantId()))
                        throw new ShoppingService.Refused(404, "NOT_FOUND", "商品不存在");
                    return new Line(
                            id,
                            q.product().productId(),
                            q.product().name(),
                            q.sku().variant(),
                            q.product().assetKey(),
                            q.product().category(),
                            q.quantity(),
                            q.sku().unitAmount(),
                            q.totalAmount(),
                            q.sku().version());
                })
                .toList();
        long total = lines.stream().mapToLong(Line::lineAmount).reduce(0, Math::addExact);
        if (total > 1000000000L) throw new IllegalArgumentException("单店订单金额超出范围");
        return new Quote(g.storeId(), g.storeName(), g.revision(), "CNY", lines, total);
    }

    private static String fingerprint(Request r, List<DraftRequest> sorted) {
        StringBuilder text = new StringBuilder().append(r.expectedRevision());
        if (r.shipping() != null)
            text.append("\nshipping:")
                    .append(r.shipping().address_id())
                    .append(':')
                    .append(r.shipping().expected_version());
        for (var line : sorted)
            text.append('\n')
                    .append(line.skuId())
                    .append(':')
                    .append(line.quantity())
                    .append(':')
                    .append(line.expectedSkuVersion());
        try {
            return HexFormat.of()
                    .formatHex(MessageDigest.getInstance("SHA-256")
                            .digest(text.toString().getBytes(StandardCharsets.UTF_8)));
        } catch (java.security.NoSuchAlgorithmException e) {
            throw new IllegalStateException(e);
        }
    }

    private Purchase replay(Command c, String hash) {
        var rows = jdbc.queryForList(
                "SELECT draft_id,kind,multiline_request_hash FROM checkout_draft WHERE merchant_id=? AND buyer_id=? AND idempotency_key=?",
                c.merchantId(),
                c.buyerId(),
                c.idempotencyKey());
        if (rows.isEmpty()) return null;
        var row = rows.getFirst();
        if (!"MULTI".equals(row.get("kind")) || !hash.equals(row.get("multiline_request_hash")))
            throw changed("IDEMPOTENCY_CONFLICT", "请求标识已用于另一份订单，请查阅原订单");
        return reads.read("draft:" + row.get("draft_id"), c.merchantId(), c.buyerId());
    }

    @Transactional(isolation = Isolation.READ_COMMITTED)
    public Purchase create(Command c) {
        if (c == null
                || c.request() == null
                || c.merchantId() == null
                || c.buyerId() == null
                || c.idempotencyKey() == null
                || !c.idempotencyKey().matches("[A-Za-z0-9_-]{1,128}")) throw new IllegalArgumentException("下单请求无效");
        var r = c.request();
        revision(r.expectedRevision());
        if (r.lines() == null
                || r.lines().stream()
                        .anyMatch(l -> l == null
                                || l.quantity() == null
                                || l.quantity() < 1
                                || l.quantity() > 100
                                || l.expectedSkuVersion() == null
                                || l.expectedSkuVersion() < 1
                                || l.expectedSkuVersion() > 9007199254740991L))
            throw new IllegalArgumentException("订单行无效");
        var ids = skus(r.lines().stream().map(DraftRequest::skuId).toList());
        var sorted = r.lines().stream()
                .sorted(Comparator.comparing(DraftRequest::skuId))
                .toList();
        String hash = fingerprint(r, sorted);
        var prior = replay(c, hash);
        var shipping = new CheckoutShipping(jdbc);
        if (prior != null) {
            shipping.freeze(prior.draftId(), r.shipping(), c.shippingSnapshot(), false);
            return prior;
        }
        shipping.requireSnapshot(r.shipping(), c.shippingSnapshot());
        var locked = jdbc.queryForList(
                "SELECT revision FROM shopping_cart WHERE merchant_id=? AND buyer_id=? FOR UPDATE",
                Long.class,
                c.merchantId(),
                c.buyerId());
        if (locked.isEmpty()) throw changed("CART_CHANGED", "购物车已更新，请重新读取");
        prior = replay(c, hash);
        if (prior != null) {
            shipping.freeze(prior.draftId(), r.shipping(), c.shippingSnapshot(), false);
            return prior;
        }
        if (locked.getFirst() != r.expectedRevision().longValue()) throw changed("CART_CHANGED", "购物车已更新，请重新读取");
        for (String sku : ids)
            jdbc.queryForList(
                    "SELECT k.sku_id FROM catalog_sku k JOIN catalog_product p ON p.product_id=k.product_id JOIN catalog_store s ON s.store_id=p.store_id WHERE k.sku_id=? FOR UPDATE",
                    String.class,
                    sku);
        var q = quote(new QuoteCommand(c.merchantId(), c.buyerId(), new QuoteRequest(r.expectedRevision(), ids)));
        for (int i = 0; i < sorted.size(); i++) {
            var original = sorted.get(i);
            var current = q.lines().get(i);
            if (original.quantity() != current.quantity()) throw changed("CART_CHANGED", "购物车数量已更新，请重新读取");
            if (original.expectedSkuVersion() != current.skuVersion()) throw changed("PRICE_CHANGED", "商品已更新，请重新确认报价");
        }
        var first = q.lines().getFirst();
        String id = UUID.randomUUID().toString();
        var now = Instant.now(clock).truncatedTo(ChronoUnit.MICROS);
        jdbc.update(
                """
            INSERT INTO checkout_draft(draft_id,merchant_id,buyer_id,idempotency_key,product_id,product_name,store_name,asset_key,sku_id,variant,quantity,unit_amount,total_amount,sku_version,created_at,expires_at,category,kind,line_count,cart_revision,multiline_request_hash)
            VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,'MULTI',?,?,?)
            """,
                id,
                c.merchantId(),
                c.buyerId(),
                c.idempotencyKey(),
                first.productId(),
                first.productName(),
                q.storeName(),
                first.assetKey(),
                first.skuId(),
                first.variant(),
                first.quantity(),
                first.unitAmount(),
                q.totalAmount(),
                first.skuVersion(),
                Timestamp.from(now),
                Timestamp.from(now.plusSeconds(900)),
                first.category(),
                q.lines().size(),
                r.expectedRevision(),
                hash);
        for (var line : q.lines()) {
            jdbc.update(
                    "INSERT INTO checkout_draft_line VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                    id,
                    line.skuId(),
                    line.productId(),
                    line.productName(),
                    line.variant(),
                    line.assetKey(),
                    line.category(),
                    line.quantity(),
                    line.unitAmount(),
                    line.lineAmount(),
                    line.skuVersion());
            if (jdbc.update(
                            "DELETE FROM shopping_cart_item WHERE merchant_id=? AND buyer_id=? AND sku_id=? AND quantity=?",
                            c.merchantId(),
                            c.buyerId(),
                            line.skuId(),
                            line.quantity())
                    != 1) throw changed("CART_CHANGED", "购物车已更新，请重新读取");
        }
        jdbc.update(
                "UPDATE shopping_cart SET revision=revision+1 WHERE merchant_id=? AND buyer_id=?",
                c.merchantId(),
                c.buyerId());
        shipping.freeze(id, r.shipping(), c.shippingSnapshot(), true);
        return reads.read("draft:" + id, c.merchantId(), c.buyerId());
    }
}
