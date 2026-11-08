package com.resolveflow.commerce.catalog;

import com.resolveflow.shared.shopping.ProductReviewWire.*;
import java.sql.ResultSet;
import java.sql.SQLException;
import java.sql.Timestamp;
import java.time.Clock;
import java.time.Instant;
import java.util.ArrayList;
import java.util.List;
import java.util.Map;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Isolation;
import org.springframework.transaction.annotation.Transactional;

@Service
public class ProductReviewService {
    private final PublicCatalogCacheInvalidation invalidations;
    private final JdbcTemplate jdbc;
    private final Clock clock;

    public ProductReviewService(JdbcTemplate jdbc, Clock clock, PublicCatalogCacheInvalidation invalidations) {
        this.invalidations = invalidations;
        this.jdbc = jdbc;
        this.clock = clock;
    }

    private static ShoppingService.Refused missing() {
        return new ShoppingService.Refused(404, "NOT_FOUND", "评价或订单行不存在");
    }

    private static ShoppingService.Refused conflict() {
        return new ShoppingService.Refused(409, "REVIEW_CHANGED", "评价已更新，请读取最新内容后重新确认");
    }

    private static void scope(String merchant, String customer) {
        if (merchant == null || merchant.isBlank() || customer == null || customer.isBlank())
            throw new IllegalArgumentException("需要可信买家归属");
    }

    private static String text(String body) {
        if (body == null || body.strip().isEmpty() || body.strip().length() > 1000)
            throw new IllegalArgumentException("文字需为1–1000字符");
        return body.strip();
    }

    private static void version(Long value) {
        if (value == null || value < 0 || value > 9007199254740990L) throw new IllegalArgumentException("评价版本无效");
    }

    private Map<String, Object> owned(String line, String merchant, String customer, boolean lock) {
        scope(merchant, customer);
        var rows = jdbc.queryForList(
                "SELECT l.*,p.product_id FROM order_line l LEFT JOIN catalog_sku k ON k.sku_id=l.sku LEFT JOIN catalog_product p ON p.product_id=k.product_id AND p.store_id=l.merchant_id WHERE l.line_id=? AND l.merchant_id=? AND l.buyer_id=?"
                        + (lock ? " FOR UPDATE" : ""),
                line,
                merchant,
                customer);
        if (rows.isEmpty()) throw missing();
        return rows.getFirst();
    }

    private static Review row(ResultSet r) throws SQLException {
        return new Review(
                r.getLong("review_id"),
                r.getString("product_id"),
                r.getString("product_name"),
                r.getString("variant"),
                r.getInt("rating"),
                r.getString("body"),
                r.getString("reply"),
                r.getLong("version"),
                r.getTimestamp("created_at").toInstant(),
                r.getTimestamp("updated_at").toInstant());
    }

    private Review forLine(String line) {
        var rows = jdbc.query("SELECT * FROM product_review WHERE line_id=?", (r, n) -> row(r), line);
        return rows.isEmpty() ? null : rows.getFirst();
    }

    private Review read(long id) {
        return jdbc.query("SELECT * FROM product_review WHERE review_id=?", (r, n) -> row(r), id)
                .getFirst();
    }

    private String blocked(Map<String, Object> line, Review existing) {
        if (existing != null) return null;
        if (line.get("product_id") == null) return "此历史订单行未关联商品，无法评价";
        if (!"PAID".equals(line.get("order_status"))) return "订单尚未完成付款";
        var statuses =
                jdbc.queryForList("SELECT status FROM shipment WHERE line_id=?", String.class, line.get("line_id"));
        return statuses.size() == 1 && "DELIVERED".equals(statuses.getFirst()) ? null : "签收后可评价";
    }

    private void changed(String product) {
        jdbc.update(
                "INSERT INTO product_review_epoch(product_id,version) VALUES(?,1) ON DUPLICATE KEY UPDATE version=version+1",
                product);
        invalidations.reviewsChanged(product);
    }

    @Transactional(readOnly = true)
    public Own own(String line, String merchant, String customer) {
        var order = owned(line, merchant, customer, false);
        var existing = forLine(line);
        var reason = blocked(order, existing);
        return new Own(reason == null, reason, existing);
    }

    @Transactional(isolation = Isolation.READ_COMMITTED)
    public Review save(String line, Command command) {
        if (command == null || command.request() == null) throw new IllegalArgumentException("需要评价请求");
        var request = command.request();
        var body = text(request.body());
        version(request.expectedVersion());
        if (request.rating() == null || request.rating() < 1 || request.rating() > 5)
            throw new IllegalArgumentException("评分须为1–5整数");
        var order = owned(line, command.merchantId(), command.buyerId(), true);
        var existing = forLine(line);
        // Serialize with merchant replies as well as competing edits of this same order line.
        if (existing != null) {
            jdbc.queryForList("SELECT review_id FROM product_review WHERE review_id=? FOR UPDATE", existing.reviewId());
            existing = forLine(line);
        }
        if (existing != null
                && existing.rating() == request.rating().intValue()
                && existing.body().equals(body)) return existing;
        if (existing == null && request.expectedVersion() != 0
                || existing != null && request.expectedVersion() != existing.version()) throw conflict();
        var reason = blocked(order, existing);
        if (reason != null) throw new ShoppingService.Refused(409, "REVIEW_NOT_ELIGIBLE", reason);
        var now = Timestamp.from(Instant.now(clock));
        if (existing == null)
            jdbc.update(
                    "INSERT INTO product_review(line_id,product_id,product_name,merchant_id,buyer_id,variant,rating,body,version,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,1,?,?)",
                    line,
                    order.get("product_id"),
                    order.get("product_name"),
                    command.merchantId(),
                    command.buyerId(),
                    order.get("variant_text"),
                    request.rating(),
                    body,
                    now,
                    now);
        else
            jdbc.update(
                    "UPDATE product_review SET rating=?,body=?,version=version+1,updated_at=? WHERE review_id=?",
                    request.rating(),
                    body,
                    now,
                    existing.reviewId());
        changed((String) order.get("product_id"));
        return forLine(line);
    }

    @Transactional(isolation = Isolation.READ_COMMITTED)
    public Review reply(long id, ReplyCommand command) {
        if (command == null
                || command.merchantId() == null
                || command.merchantId().isBlank()
                || command.request() == null) throw new IllegalArgumentException("需要可信商家及回复");
        var request = command.request();
        var body = text(request.body());
        version(request.expectedVersion());
        var rows = jdbc.query(
                "SELECT * FROM product_review WHERE review_id=? AND merchant_id=? FOR UPDATE",
                (r, n) -> row(r),
                id,
                command.merchantId());
        if (rows.isEmpty()) throw missing();
        var existing = rows.getFirst();
        if (body.equals(existing.reply())) return existing;
        if (request.expectedVersion() != existing.version()) throw conflict();
        jdbc.update(
                "UPDATE product_review SET reply=?,version=version+1,updated_at=? WHERE review_id=?",
                body,
                Timestamp.from(Instant.now(clock)),
                id);
        changed(existing.productId());
        return read(id);
    }

    @Transactional(readOnly = true, timeout = 1)
    public long publicEpoch(String product) {
        var rows = jdbc.queryForList(
                "SELECT COALESCE(e.version,0) AS epoch FROM catalog_product p JOIN catalog_store s ON s.store_id=p.store_id LEFT JOIN product_review_epoch e ON e.product_id=p.product_id WHERE p.product_id=? AND p.listed=TRUE AND s.enabled=TRUE AND EXISTS(SELECT 1 FROM catalog_sku k WHERE k.product_id=p.product_id AND k.listed=TRUE)",
                Long.class,
                product);
        if (rows.isEmpty()) throw missing();
        return rows.getFirst();
    }

    static int limit(Long before, Integer limit) {
        int size = limit == null ? 10 : limit;
        if (size < 1 || size > 20 || before != null && before < 1) throw new IllegalArgumentException("评价分页参数无效");
        return size;
    }

    private Page page(String column, String id, Long before, int size, boolean summary) {
        var args = new ArrayList<Object>(List.of(id));
        var sql = "SELECT * FROM product_review WHERE " + column + "=?";
        if (before != null) {
            sql += " AND review_id<?";
            args.add(before);
        }
        sql += " ORDER BY review_id DESC LIMIT ?";
        args.add(size + 1);
        var rows = jdbc.query(sql, (r, n) -> row(r), args.toArray());
        var shown = List.copyOf(rows.subList(0, Math.min(size, rows.size())));
        Summary totals = null;
        if (summary) {
            long[] stars = new long[5];
            jdbc.query(
                    "SELECT rating,COUNT(*) AS total FROM product_review WHERE product_id=? GROUP BY rating",
                    (org.springframework.jdbc.core.RowCallbackHandler)
                            r -> stars[5 - r.getInt("rating")] = r.getLong("total"),
                    id);
            long count = java.util.Arrays.stream(stars).sum();
            long sum = 0;
            for (int i = 0; i < 5; i++) sum += stars[i] * (5 - i);
            totals = new Summary(
                    count,
                    count == 0 ? null : Math.round(10.0 * sum / count) / 10.0,
                    java.util.Arrays.stream(stars).boxed().toList());
        }
        return new Page(shown, totals, rows.size() > size ? shown.getLast().reviewId() : null);
    }

    @Transactional(readOnly = true, isolation = Isolation.REPEATABLE_READ, timeout = 1)
    public Page publicPage(String product, Long before, Integer limit) {
        int size = limit(before, limit);
        publicEpoch(product);
        return page("product_id", product, before, size, true);
    }

    @Transactional(readOnly = true)
    public Page merchantPage(String merchant, Long before, Integer limit) {
        if (merchant == null || merchant.isBlank()) throw new IllegalArgumentException("需要可信商家");
        return page("merchant_id", merchant, before, limit(before, limit), false);
    }
}
