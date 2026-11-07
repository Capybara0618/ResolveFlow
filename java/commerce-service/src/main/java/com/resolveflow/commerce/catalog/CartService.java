package com.resolveflow.commerce.catalog;

import com.resolveflow.shared.shopping.CartWire.*;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.util.HexFormat;
import java.util.List;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Isolation;
import org.springframework.transaction.annotation.Transactional;

@Service
public class CartService {
    private static final long MAX_VERSION = 9007199254740991L;
    private final JdbcTemplate jdbc;
    private final ShoppingService shop;

    public CartService(JdbcTemplate jdbc, ShoppingService shop) {
        this.jdbc = jdbc;
        this.shop = shop;
    }

    private static void scope(String merchant, String customer) {
        if (merchant == null
                || customer == null
                || !merchant.matches("[A-Za-z0-9_-]{1,64}")
                || !customer.matches("[A-Za-z0-9_-]{1,64}")) throw new IllegalArgumentException("需要可信买家归属");
    }

    private static ShoppingService.Refused conflict(String code, String message) {
        return new ShoppingService.Refused(409, code, message);
    }

    private static String hash(Request r) {
        try {
            return HexFormat.of()
                    .formatHex(MessageDigest.getInstance("SHA-256")
                            .digest((r.skuId() + "\n" + r.quantity() + "\n" + r.expectedRevision() + "\n"
                                            + r.expectedSkuVersion())
                                    .getBytes(StandardCharsets.UTF_8)));
        } catch (java.security.NoSuchAlgorithmException e) {
            throw new IllegalStateException(e);
        }
    }

    @Transactional(readOnly = true)
    public Group read(String merchant, String customer) {
        scope(merchant, customer);
        var names = jdbc.queryForList("SELECT name FROM catalog_store WHERE store_id=?", String.class, merchant);
        if (names.isEmpty()) throw new ShoppingService.Refused(404, "NOT_FOUND", "店铺不存在");
        var revisions = jdbc.queryForList(
                "SELECT revision FROM shopping_cart WHERE merchant_id=? AND buyer_id=?",
                Long.class,
                merchant,
                customer);
        List<Item> items = jdbc.query(
                """
            SELECT i.*,k.unit_amount,k.max_quantity,k.version,p.product_id,p.name,p.asset_key,k.variant,
              CASE WHEN s.enabled=FALSE THEN 'STORE_DISABLED'
                WHEN p.listed=FALSE OR k.listed=FALSE THEN 'DELISTED'
                WHEN i.quantity>k.max_quantity THEN 'QUANTITY_EXCEEDED' ELSE 'AVAILABLE' END AS availability
            FROM shopping_cart_item i JOIN catalog_sku k ON k.sku_id=i.sku_id
            JOIN catalog_product p ON p.product_id=k.product_id JOIN catalog_store s ON s.store_id=p.store_id
            WHERE i.merchant_id=? AND i.buyer_id=? ORDER BY i.sku_id
            """,
                (rs, n) -> new Item(
                        rs.getString("sku_id"),
                        rs.getString("product_id"),
                        rs.getString("name"),
                        rs.getString("variant"),
                        rs.getString("asset_key"),
                        rs.getInt("quantity"),
                        rs.getLong("unit_amount"),
                        Math.multiplyExact(rs.getLong("unit_amount"), rs.getInt("quantity")),
                        rs.getInt("max_quantity"),
                        rs.getLong("version"),
                        rs.getLong("version") != rs.getLong("observed_sku_version"),
                        rs.getString("availability")),
                merchant,
                customer);
        return new Group(merchant, names.getFirst(), revisions.isEmpty() ? 0 : revisions.getFirst(), "CNY", items);
    }

    @Transactional(isolation = Isolation.READ_COMMITTED)
    public Receipt write(Command c) {
        if (c == null
                || c.request() == null
                || c.idempotencyKey() == null
                || !c.idempotencyKey().matches("[A-Za-z0-9_-]{1,128}")) throw new IllegalArgumentException("缺少有效请求标识");
        scope(c.merchantId(), c.buyerId());
        var r = c.request();
        if (r.skuId() == null
                || !r.skuId().matches("[A-Za-z0-9_-]{1,64}")
                || r.quantity() == null
                || r.quantity() < 0
                || r.quantity() > 100
                || r.expectedRevision() == null
                || r.expectedRevision() < 0
                || r.expectedRevision() >= MAX_VERSION
                || (r.quantity() > 0
                        && (r.expectedSkuVersion() == null
                                || r.expectedSkuVersion() < 1
                                || r.expectedSkuVersion() > MAX_VERSION))
                || (r.quantity() == 0 && r.expectedSkuVersion() != null))
            throw new IllegalArgumentException("购物车数量或版本无效");
        // A single scope lock serializes CAS, limit checks and idempotency; retained when the cart is empty.
        jdbc.update(
                "INSERT INTO shopping_cart(merchant_id,buyer_id) VALUES(?,?) ON DUPLICATE KEY UPDATE revision=revision",
                c.merchantId(),
                c.buyerId());
        long revision = jdbc.queryForObject(
                "SELECT revision FROM shopping_cart WHERE merchant_id=? AND buyer_id=? FOR UPDATE",
                Long.class,
                c.merchantId(),
                c.buyerId());
        var prior = jdbc.queryForList(
                "SELECT request_hash,result_revision FROM shopping_cart_request WHERE merchant_id=? AND buyer_id=? AND idempotency_key=?",
                c.merchantId(),
                c.buyerId(),
                c.idempotencyKey());
        String fingerprint = hash(r);
        if (!prior.isEmpty()) {
            var saved = prior.getFirst();
            if (!fingerprint.equals(saved.get("request_hash")))
                throw conflict("IDEMPOTENCY_CONFLICT", "请求标识已用于另一项购物车操作");
            return new Receipt(c.merchantId(), ((Number) saved.get("result_revision")).longValue());
        }
        if (revision != r.expectedRevision()) throw conflict("CART_CHANGED", "购物车已更新，请重新读取后操作");
        if (r.quantity() == 0) {
            if (jdbc.update(
                            "DELETE FROM shopping_cart_item WHERE merchant_id=? AND buyer_id=? AND sku_id=?",
                            c.merchantId(),
                            c.buyerId(),
                            r.skuId())
                    != 1) throw new ShoppingService.Refused(404, "NOT_FOUND", "购物车商品不存在");
        } else {
            var locked = jdbc.queryForList(
                    "SELECT k.sku_id FROM catalog_sku k JOIN catalog_product p ON p.product_id=k.product_id JOIN catalog_store s ON s.store_id=p.store_id WHERE k.sku_id=? FOR UPDATE",
                    String.class,
                    r.skuId());
            if (locked.isEmpty()) throw new ShoppingService.Refused(404, "NOT_FOUND", "商品不存在");
            var q = shop.quote(new com.resolveflow.shared.shopping.ShoppingWire.QuoteRequest(r.skuId(), r.quantity()));
            if (!q.product().storeId().equals(c.merchantId()))
                throw new ShoppingService.Refused(404, "NOT_FOUND", "商品不存在");
            if (q.sku().version() != r.expectedSkuVersion()) throw conflict("PRICE_CHANGED", "商品已更新，请重新确认价格和规格");
            int existing = jdbc.queryForObject(
                    "SELECT COUNT(*) FROM shopping_cart_item WHERE merchant_id=? AND buyer_id=? AND sku_id=?",
                    Integer.class,
                    c.merchantId(),
                    c.buyerId(),
                    r.skuId());
            int count = jdbc.queryForObject(
                    "SELECT COUNT(*) FROM shopping_cart_item WHERE merchant_id=? AND buyer_id=?",
                    Integer.class,
                    c.merchantId(),
                    c.buyerId());
            if (existing == 0 && count >= 20) throw conflict("CART_LIMIT", "每家店铺最多保留20种商品规格");
            jdbc.update(
                    "INSERT INTO shopping_cart_item(merchant_id,buyer_id,sku_id,quantity,observed_sku_version) VALUES(?,?,?,?,?) ON DUPLICATE KEY UPDATE quantity=VALUES(quantity),observed_sku_version=VALUES(observed_sku_version)",
                    c.merchantId(),
                    c.buyerId(),
                    r.skuId(),
                    r.quantity(),
                    r.expectedSkuVersion());
        }
        jdbc.update(
                "UPDATE shopping_cart SET revision=revision+1 WHERE merchant_id=? AND buyer_id=?",
                c.merchantId(),
                c.buyerId());
        jdbc.update(
                "INSERT INTO shopping_cart_request VALUES(?,?,?,?,?)",
                c.merchantId(),
                c.buyerId(),
                c.idempotencyKey(),
                fingerprint,
                revision + 1);
        return new Receipt(c.merchantId(), revision + 1);
    }
}
