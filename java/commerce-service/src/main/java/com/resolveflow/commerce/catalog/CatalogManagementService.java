package com.resolveflow.commerce.catalog;

import com.resolveflow.shared.shopping.ManagementWire.*;
import java.util.HashSet;
import java.util.List;
import java.util.Objects;
import java.util.UUID;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

@Service
public class CatalogManagementService {
    private final PublicCatalogCacheInvalidation invalidations;
    private final JdbcTemplate jdbc;

    public CatalogManagementService(JdbcTemplate jdbc, PublicCatalogCacheInvalidation invalidations) {
        this.invalidations = invalidations;
        this.jdbc = jdbc;
    }

    private static ShoppingService.Refused invalid(String message) {
        return new ShoppingService.Refused(400, "INVALID_ARGUMENT", message);
    }

    private static ShoppingService.Refused missing() {
        return new ShoppingService.Refused(404, "NOT_FOUND", "本店商品不存在");
    }

    private static ShoppingService.Refused conflict() {
        return new ShoppingService.Refused(409, "VERSION_CONFLICT", "商品或商家已更新，请刷新后重新编辑");
    }

    private static void text(String value, int max) {
        if (value == null || value.isBlank() || value.length() > max) throw invalid("文字内容为空或超出长度限制");
    }

    @Transactional
    public StoreSync sync(StoreSync request) {
        if (request == null
                || request.storeId() == null
                || !request.storeId().matches("[A-Za-z0-9_-]{1,64}")
                || request.version() < 1) throw invalid("商家同步参数无效");
        text(request.name(), 120);
        text(request.description(), 500);
        // Serialize creation as well as updates under a database unique-key lock.
        jdbc.update(
                "INSERT IGNORE INTO catalog_store(store_id,name,description,enabled,version) VALUES (?,?,?,FALSE,0)",
                request.storeId(),
                request.name(),
                request.description());
        var current = jdbc.query(
                        "SELECT * FROM catalog_store WHERE store_id=? FOR UPDATE",
                        (rs, n) -> new StoreSync(
                                rs.getString("store_id"),
                                rs.getString("name"),
                                rs.getString("description"),
                                rs.getBoolean("enabled"),
                                rs.getLong("version")),
                        request.storeId())
                .getFirst();
        if (current.version() > request.version()) throw conflict();
        if (current.version() == request.version()) {
            if (!current.equals(request)) throw conflict();
            return current;
        }
        jdbc.update(
                "UPDATE catalog_store SET name=?,description=?,enabled=?,version=? WHERE store_id=?",
                request.name(),
                request.description(),
                request.enabled(),
                request.version(),
                request.storeId());
        invalidations.storeChanged(request.storeId());
        return request;
    }

    public Products list(String merchant, String after, Integer supplied) {
        int limit = supplied == null ? 24 : supplied;
        if (limit < 1 || limit > 48 || after != null && after.length() > 64) throw invalid("分页参数无效");
        var ids = jdbc.queryForList(
                "SELECT product_id FROM catalog_product WHERE store_id=? AND product_id>? ORDER BY product_id LIMIT ?",
                String.class,
                merchant,
                after == null ? "" : after,
                limit + 1);
        var shown = ids.subList(0, Math.min(ids.size(), limit));
        return new Products(
                shown.stream().map(id -> read(merchant, id)).toList(), ids.size() > limit ? shown.getLast() : null);
    }

    public Product read(String merchant, String id) {
        var rows = jdbc.query(
                "SELECT * FROM catalog_product WHERE store_id=? AND product_id=?",
                (rs, n) -> new Product(
                        rs.getString("product_id"),
                        rs.getString("store_id"),
                        rs.getString("name"),
                        rs.getString("description"),
                        rs.getString("category"),
                        rs.getString("asset_key"),
                        rs.getBoolean("listed"),
                        rs.getLong("version"),
                        List.of()),
                merchant,
                id);
        if (rows.isEmpty()) throw missing();
        var p = rows.getFirst();
        var skus = jdbc.query(
                "SELECT * FROM catalog_sku WHERE product_id=? ORDER BY sku_id",
                (rs, n) -> new Sku(
                        rs.getString("sku_id"),
                        rs.getString("variant"),
                        rs.getLong("unit_amount"),
                        rs.getInt("max_quantity"),
                        rs.getBoolean("listed"),
                        rs.getLong("version")),
                id);
        return new Product(
                p.product_id(),
                p.store_id(),
                p.name(),
                p.description(),
                p.category(),
                p.asset_key(),
                p.listed(),
                p.version(),
                skus);
    }

    private static void validate(ProductCommand command) {
        if (command == null || command.product() == null) throw invalid("请填写商品信息");
        text(command.merchantId(), 64);
        text(command.actor(), 120);
        var p = command.product();
        text(p.name(), 120);
        text(p.description(), 1000);
        if (!List.of("electronics", "home", "outdoor").contains(Objects.toString(p.category(), ""))
                || p.assetKey() == null
                || !p.assetKey().matches("[a-z][a-z0-9_-]{0,31}")
                || p.listed() == null
                || p.skus() == null
                || p.skus().isEmpty()
                || p.skus().size() > 20) throw invalid("商品分类、插画或规格无效");
        var seen = new HashSet<String>();
        for (var s : p.skus()) {
            if (s == null) throw invalid("规格无效");
            text(s.variant(), 120);
            if (s.unitAmount() == null
                    || s.unitAmount() < 1
                    || s.unitAmount() > 100000000
                    || s.maxQuantity() == null
                    || s.maxQuantity() < 1
                    || s.maxQuantity() > 100
                    || s.listed() == null) throw invalid("价格需整数分，数量上限需1–100");
            if (s.skuId() != null && (!s.skuId().matches("[A-Za-z0-9_-]{1,64}") || !seen.add(s.skuId())))
                throw invalid("规格标识重复或无效");
        }
        if (p.listed() && p.skus().stream().noneMatch(s -> s.listed())) throw invalid("上架商品至少有一个上架规格");
    }

    @Transactional
    public Product save(String id, ProductCommand command) {
        validate(command);
        var p = command.product();
        if (jdbc.queryForList(
                        "SELECT store_id FROM catalog_store WHERE store_id=? AND enabled=TRUE FOR UPDATE",
                        String.class,
                        command.merchantId())
                .isEmpty()) throw invalid("商家未启用");
        boolean create = id == null;
        if (create) {
            if (p.expectedVersion() != null || p.skus().stream().anyMatch(s -> s.skuId() != null))
                throw invalid("新增商品不能携带已有商品或规格版本");
            id = "P-" + UUID.randomUUID();
            jdbc.update(
                    "INSERT INTO catalog_product(product_id,store_id,name,description,category,asset_key,listed) VALUES (?,?,?,?,?,?,?)",
                    id,
                    command.merchantId(),
                    p.name().trim(),
                    p.description().trim(),
                    p.category(),
                    p.assetKey(),
                    p.listed());
        } else {
            if (jdbc.queryForList(
                            "SELECT product_id FROM catalog_product WHERE store_id=? AND product_id=? FOR UPDATE",
                            String.class,
                            command.merchantId(),
                            id)
                    .isEmpty()) throw missing();
            var before = read(command.merchantId(), id);
            if (p.expectedVersion() == null || p.expectedVersion() != before.version()) throw conflict();
            var suppliedIds = p.skus().stream()
                    .map(SkuWrite::skuId)
                    .filter(Objects::nonNull)
                    .toList();
            var existingIds = before.skus().stream().map(Sku::sku_id).toList();
            if (suppliedIds.size() != existingIds.size()
                    || !new HashSet<>(suppliedIds).equals(new HashSet<>(existingIds)))
                throw invalid("已有规格不能删除或移入；停用请设置下架");
            jdbc.update(
                    "UPDATE catalog_product SET name=?,description=?,category=?,asset_key=?,listed=?,version=version+1 WHERE product_id=?",
                    p.name().trim(),
                    p.description().trim(),
                    p.category(),
                    p.assetKey(),
                    p.listed(),
                    id);
        }
        for (var s : p.skus()) {
            if (s.skuId() == null)
                jdbc.update(
                        "INSERT INTO catalog_sku(sku_id,product_id,variant,unit_amount,max_quantity,listed) VALUES (?,?,?,?,?,?)",
                        "SKU-" + UUID.randomUUID(),
                        id,
                        s.variant().trim(),
                        s.unitAmount(),
                        s.maxQuantity(),
                        s.listed());
            else
                jdbc.update(
                        "UPDATE catalog_sku SET variant=?,unit_amount=?,max_quantity=?,listed=?,version=version+1 WHERE product_id=? AND sku_id=?",
                        s.variant().trim(),
                        s.unitAmount(),
                        s.maxQuantity(),
                        s.listed(),
                        id,
                        s.skuId());
        }
        var result = read(command.merchantId(), id);
        jdbc.update(
                "INSERT INTO catalog_management_audit(store_id,product_id,actor,action,version) VALUES (?,?,?,?,?)",
                command.merchantId(),
                id,
                command.actor(),
                create ? "CREATED" : "UPDATED",
                result.version());
        invalidations.productChanged(id);
        return result;
    }
}
