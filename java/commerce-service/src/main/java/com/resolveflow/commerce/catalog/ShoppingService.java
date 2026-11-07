package com.resolveflow.commerce.catalog;

import com.resolveflow.shared.shopping.ShoppingWire.*;
import java.sql.ResultSet;
import java.sql.SQLException;
import java.sql.Timestamp;
import java.time.Clock;
import java.time.Instant;
import java.time.temporal.ChronoUnit;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.List;
import java.util.UUID;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

@Service
public class ShoppingService {
    private final JdbcTemplate jdbc;
    private final Clock clock;

    public ShoppingService(JdbcTemplate jdbc, Clock clock) {
        this.jdbc = jdbc;
        this.clock = clock;
    }

    public static class Refused extends RuntimeException {
        private static final long serialVersionUID = 1L;
        public final int status;
        public final String code;

        public Refused(int status, String code, String message) {
            super(message);
            this.status = status;
            this.code = code;
        }
    }

    private static Refused missing() {
        return new Refused(404, "NOT_FOUND", "商品或订单不存在");
    }

    public List<Store> stores() {
        return jdbc.query(
                "SELECT * FROM catalog_store WHERE enabled=TRUE ORDER BY store_id",
                (rs, n) -> new Store(rs.getString("store_id"), rs.getString("name"), rs.getString("description")));
    }

    public Store store(String id) {
        return stores().stream().filter(s -> s.storeId().equals(id)).findFirst().orElseThrow(ShoppingService::missing);
    }

    @Transactional(readOnly = true, isolation = org.springframework.transaction.annotation.Isolation.REPEATABLE_READ)
    public Products products(String query, String category, String store, String after, Integer suppliedLimit) {
        int limit = suppliedLimit == null ? 24 : suppliedLimit;
        if (limit < 1
                || limit > 48
                || query != null && query.length() > 80
                || after != null && after.length() > 64
                || store != null && store.length() > 64) throw new IllegalArgumentException("查询或分页参数超出范围");
        if (category != null && !List.of("electronics", "home", "outdoor").contains(category))
            throw new IllegalArgumentException("分类无效");
        String sql =
                "SELECT p.*,s.name AS store_name,JSON_UNQUOTE(JSON_EXTRACT(presentation.images,'$[0]')) AS cover_image_id FROM catalog_product p JOIN catalog_store s ON s.store_id=p.store_id LEFT JOIN catalog_product_presentation presentation ON presentation.product_id=p.product_id WHERE p.listed=TRUE AND s.enabled=TRUE AND EXISTS(SELECT 1 FROM catalog_sku k WHERE k.product_id=p.product_id AND k.listed=TRUE)";
        List<Object> args = new ArrayList<>();
        if (query != null && !query.isBlank()) {
            sql += " AND LOCATE(?,p.name)>0";
            args.add(query.trim());
        }
        if (category != null) {
            sql += " AND p.category=?";
            args.add(category);
        }
        if (store != null) {
            sql += " AND p.store_id=?";
            args.add(store);
        }
        if (after != null) {
            sql += " AND p.product_id>?";
            args.add(after);
        }
        sql += " ORDER BY p.product_id LIMIT ?";
        args.add(limit + 1);
        var products = jdbc.query(sql, (rs, n) -> productRow(rs), args.toArray());
        boolean more = products.size() > limit;
        var shown = products.subList(0, Math.min(limit, products.size()));
        if (shown.isEmpty()) return new Products(List.of(), null);
        var skus = new HashMap<String, List<Sku>>();
        String placeholders = String.join(",", java.util.Collections.nCopies(shown.size(), "?"));
        jdbc.query(
                "SELECT * FROM catalog_sku WHERE listed=TRUE AND product_id IN (" + placeholders + ") ORDER BY sku_id",
                (org.springframework.jdbc.core.RowCallbackHandler)
                        rs -> skus.computeIfAbsent(rs.getString("product_id"), ignored -> new ArrayList<>())
                                .add(skuRow(rs)),
                shown.stream().map(Product::productId).toArray());
        return new Products(
                shown.stream().map(p -> priced(p, skus.get(p.productId()))).toList(),
                more ? shown.getLast().productId() : null);
    }

    private static Product productRow(ResultSet rs) throws SQLException {
        return new Product(
                rs.getString("product_id"),
                rs.getString("store_id"),
                rs.getString("store_name"),
                rs.getString("name"),
                rs.getString("description"),
                rs.getString("category"),
                rs.getString("asset_key"),
                0,
                "CNY",
                List.of(),
                rs.getString("cover_image_id"));
    }

    private static Sku skuRow(ResultSet rs) throws SQLException {
        return new Sku(
                rs.getString("sku_id"),
                rs.getString("variant"),
                rs.getLong("unit_amount"),
                rs.getInt("max_quantity"),
                rs.getLong("version"));
    }

    private static Product priced(Product p, List<Sku> skus) {
        if (skus == null || skus.isEmpty()) throw missing();
        return new Product(
                p.productId(),
                p.storeId(),
                p.storeName(),
                p.name(),
                p.description(),
                p.category(),
                p.assetKey(),
                skus.stream().mapToLong(Sku::unitAmount).min().orElseThrow(),
                "CNY",
                List.copyOf(skus),
                p.coverImageId());
    }

    public Product product(String id) {
        var rows = jdbc.query(
                "SELECT p.*,s.name AS store_name,JSON_UNQUOTE(JSON_EXTRACT(presentation.images,'$[0]')) AS cover_image_id FROM catalog_product p JOIN catalog_store s ON s.store_id=p.store_id LEFT JOIN catalog_product_presentation presentation ON presentation.product_id=p.product_id WHERE p.product_id=? AND p.listed=TRUE AND s.enabled=TRUE",
                (rs, n) -> productRow(rs),
                id);
        if (rows.isEmpty()) throw missing();
        var p = rows.getFirst();
        var skus = jdbc.query(
                "SELECT * FROM catalog_sku WHERE product_id=? AND listed=TRUE ORDER BY sku_id",
                (rs, n) -> skuRow(rs),
                id);
        return priced(p, skus);
    }

    public Quote quote(QuoteRequest request) {
        if (request == null || request.skuId() == null || !request.skuId().matches("[A-Za-z0-9_-]{1,64}"))
            throw new IllegalArgumentException("规格无效");
        var ids = jdbc.queryForList(
                "SELECT product_id FROM catalog_sku WHERE sku_id=? AND listed=TRUE", String.class, request.skuId());
        if (ids.isEmpty()) throw missing();
        var p = product(ids.getFirst());
        var sku = p.skus().stream()
                .filter(s -> s.skuId().equals(request.skuId()))
                .findFirst()
                .orElseThrow(ShoppingService::missing);
        if (request.quantity() == null || request.quantity() < 1 || request.quantity() > sku.maxQuantity())
            throw new IllegalArgumentException("数量必须在1到" + sku.maxQuantity() + "之间");
        return new Quote(p, sku, request.quantity(), Math.multiplyExact(sku.unitAmount(), request.quantity()), "CNY");
    }

    private record Saved(Draft draft, long version, boolean multiline) {}

    private Saved saved(ResultSet rs) throws SQLException {
        Instant created = rs.getTimestamp("created_at").toInstant(),
                expires = rs.getTimestamp("expires_at").toInstant();
        return new Saved(
                new Draft(
                        rs.getString("draft_id"),
                        rs.getString("merchant_id"),
                        rs.getString("store_name"),
                        rs.getString("product_id"),
                        rs.getString("product_name"),
                        rs.getString("asset_key"),
                        rs.getString("sku_id"),
                        rs.getString("variant"),
                        rs.getInt("quantity"),
                        rs.getLong("unit_amount"),
                        rs.getLong("total_amount"),
                        "CNY",
                        "EXPIRED".equals(rs.getString("close_reason"))
                                        || rs.getString("status").equals("WAITING_PAYMENT")
                                                && !Instant.now(clock).isBefore(expires)
                                ? "EXPIRED"
                                : rs.getString("status"),
                        created,
                        expires),
                rs.getLong("sku_version"),
                "MULTI".equals(rs.getString("kind")));
    }

    public Draft read(String id, String merchant, String customer) {
        var rows = jdbc.query(
                "SELECT * FROM checkout_draft WHERE draft_id=? AND merchant_id=? AND buyer_id=?",
                (rs, n) -> saved(rs),
                id,
                merchant,
                customer);
        if (rows.isEmpty()) throw missing();
        return rows.getFirst().draft();
    }

    private Draft replay(Saved s, DraftRequest r) {
        if (s.multiline()
                || !s.draft().skuId().equals(r.skuId())
                || s.draft().quantity() != r.quantity()
                || s.version() != r.expectedSkuVersion())
            throw new Refused(409, "IDEMPOTENCY_CONFLICT", "请求标识已用于另一份订单，请查阅原草稿");
        return s.draft();
    }

    @Transactional(isolation = org.springframework.transaction.annotation.Isolation.READ_COMMITTED)
    public Draft create(DraftCommand command) {
        if (command == null
                || command.request() == null
                || command.merchantId() == null
                || command.buyerId() == null
                || command.idempotencyKey() == null
                || !command.idempotencyKey().matches("[A-Za-z0-9_-]{1,128}"))
            throw new IllegalArgumentException("创建订单参数无效");
        var r = command.request();
        if (r.quantity() == null
                || r.quantity() < 1
                || r.quantity() > 100
                || r.expectedSkuVersion() == null
                || r.expectedSkuVersion() < 1
                || r.expectedSkuVersion() > 9007199254740991L) throw new IllegalArgumentException("数量或规格版本无效");
        var existing = jdbc.query(
                "SELECT * FROM checkout_draft WHERE merchant_id=? AND buyer_id=? AND idempotency_key=?",
                (rs, n) -> saved(rs),
                command.merchantId(),
                command.buyerId(),
                command.idempotencyKey());
        var shipping = new CheckoutShipping(jdbc);
        if (!existing.isEmpty()) {
            var prior = replay(existing.getFirst(), r);
            shipping.freeze(prior.draftId(), r.shipping(), command.shippingSnapshot(), false);
            return prior;
        }
        shipping.requireSnapshot(r.shipping(), command.shippingSnapshot());
        // Lock all pricing/listing authorities; no external calls inside the transaction.
        var locked = jdbc.queryForList(
                "SELECT k.sku_id FROM catalog_sku k JOIN catalog_product p ON p.product_id=k.product_id JOIN catalog_store s ON s.store_id=p.store_id WHERE k.sku_id=? FOR UPDATE",
                String.class,
                r.skuId());
        if (locked.isEmpty()) throw missing();
        var q = quote(new QuoteRequest(r.skuId(), r.quantity()));
        if (!q.product().storeId().equals(command.merchantId())) throw missing();
        if (q.sku().version() != r.expectedSkuVersion()) throw new Refused(409, "PRICE_CHANGED", "商品价格或规格已更新，请重新确认报价");
        Instant now = Instant.now(clock).truncatedTo(ChronoUnit.MICROS), expires = now.plusSeconds(900);
        jdbc.update(
                """
            INSERT INTO checkout_draft(draft_id,merchant_id,buyer_id,idempotency_key,product_id,product_name,store_name,asset_key,sku_id,variant,quantity,unit_amount,total_amount,sku_version,created_at,expires_at,category)
            VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?) ON DUPLICATE KEY UPDATE draft_id=draft_id
            """,
                UUID.randomUUID().toString(),
                command.merchantId(),
                command.buyerId(),
                command.idempotencyKey(),
                q.product().productId(),
                q.product().name(),
                q.product().storeName(),
                q.product().assetKey(),
                q.sku().skuId(),
                q.sku().variant(),
                q.quantity(),
                q.sku().unitAmount(),
                q.totalAmount(),
                q.sku().version(),
                Timestamp.from(now),
                Timestamp.from(expires),
                q.product().category());
        var finalRow = jdbc.query(
                        "SELECT * FROM checkout_draft WHERE merchant_id=? AND buyer_id=? AND idempotency_key=? FOR UPDATE",
                        (rs, n) -> saved(rs),
                        command.merchantId(),
                        command.buyerId(),
                        command.idempotencyKey())
                .getFirst();
        var result = replay(finalRow, r);
        shipping.freeze(result.draftId(), r.shipping(), command.shippingSnapshot(), true);
        return result;
    }
}
