package com.resolveflow.commerce.catalog;

import com.resolveflow.shared.shopping.PresentationWire.*;
import java.util.*;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import tools.jackson.databind.ObjectMapper;

@Service
public class PresentationService {
    private final PublicCatalogCacheInvalidation invalidations;
    private final JdbcTemplate db;
    private final ObjectMapper json = new ObjectMapper();

    public PresentationService(JdbcTemplate db, PublicCatalogCacheInvalidation invalidations) {
        this.invalidations = invalidations;
        this.db = db;
    }

    private static ShoppingService.Refused missing() {
        return new ShoppingService.Refused(404, "NOT_FOUND", "商品或店铺不存在");
    }

    private static void text(String s, int max) {
        if (s == null
                || s.length() > max
                || s.chars().anyMatch(c -> Character.isISOControl(c) && c != '\n' && c != '\r' && c != '\t'))
            throw new IllegalArgumentException("资料内容无效或超出长度限制");
    }

    private static void version(long current, Long expected) {
        if (expected == null || expected < 0) throw new IllegalArgumentException("请提供资料版本");
        if (current != expected) throw new ShoppingService.Refused(409, "VERSION_CONFLICT", "资料已更新，请刷新后重新编辑");
    }

    private static void media(String id) {
        if (id == null || !id.matches("[a-f0-9]{8}(-[a-f0-9]{4}){3}-[a-f0-9]{12}"))
            throw new IllegalArgumentException("图片标识无效");
    }

    private void productScope(String id, String merchant, boolean lock) {
        if (db.queryForList(
                        "SELECT product_id FROM catalog_product p JOIN catalog_store s ON s.store_id=p.store_id WHERE p.product_id=? "
                                + (merchant == null ? "AND p.listed=TRUE AND s.enabled=TRUE" : "AND p.store_id=?")
                                + (lock ? " FOR UPDATE" : ""),
                        String.class,
                        merchant == null ? new Object[] {id} : new Object[] {id, merchant})
                .isEmpty()) throw missing();
    }

    private void storeScope(String id, boolean publicRead, boolean lock) {
        if (db.queryForList(
                        "SELECT store_id FROM catalog_store WHERE store_id=?" + (publicRead ? " AND enabled=TRUE" : "")
                                + (lock ? " FOR UPDATE" : ""),
                        String.class,
                        id)
                .isEmpty()) throw missing();
    }

    public Product product(String id, String merchant) {
        productScope(id, merchant, false);
        var rows = db.queryForList("SELECT * FROM catalog_product_presentation WHERE product_id=?", id);
        if (rows.isEmpty()) return new Product(id, 0, List.of(), List.of(), "", "");
        var r = rows.getFirst();
        return new Product(
                id,
                ((Number) r.get("version")).longValue(),
                Arrays.asList(json.readValue(r.get("images").toString(), String[].class)),
                Arrays.asList(json.readValue(r.get("specifications").toString(), Spec[].class)),
                r.get("shipping_note").toString(),
                r.get("aftercare_note").toString(),
                variantImages(r.get("variant_images")));
    }

    private Map<String, String> variantImages(Object raw) {
        if (raw == null) return Map.of();
        return json.readValue(raw.toString(), new tools.jackson.core.type.TypeReference<Map<String, String>>() {});
    }

    @Transactional
    public Product saveProduct(String id, ProductCommand command) {
        var r = command.request();
        if (r == null
                || r.images() == null
                || r.specifications() == null
                || r.images().size() > 8
                || r.specifications().size() > 20
                || new HashSet<>(r.images()).size() != r.images().size())
            throw new IllegalArgumentException("最多8张图片和20项参数");
        r.images().forEach(PresentationService::media);
        for (var spec : r.specifications()) {
            if (spec == null
                    || spec.name() == null
                    || spec.name().isBlank()
                    || spec.value() == null
                    || spec.value().isBlank()) throw new IllegalArgumentException("请填写完整参数");
            text(spec.name(), 40);
            text(spec.value(), 160);
        }
        text(r.shipping_note(), 500);
        text(r.aftercare_note(), 1000);
        productScope(id, command.merchant_id(), true);
        var current = product(id, command.merchant_id());
        version(current.version(), r.expected_version());
        var mapping = new LinkedHashMap<String, String>();
        if (r.variant_images() == null)
            current.variant_images().forEach((variant, image) -> {
                if (r.images().contains(image)) mapping.put(variant, image);
            });
        else mapping.putAll(r.variant_images());
        var variants = db.queryForList("SELECT variant FROM catalog_sku WHERE product_id=?", String.class, id);
        if (mapping.size() > variants.size()
                || mapping.entrySet().stream()
                        .anyMatch(e ->
                                !variants.contains(e.getKey()) || !r.images().contains(e.getValue())))
            throw new IllegalArgumentException("款式图片必须属于当前商品相册及有效款式");
        db.update(
                "INSERT INTO catalog_product_presentation(product_id,version,images,specifications,shipping_note,aftercare_note,variant_images) VALUES(?,?,?,?,?,?,?) ON DUPLICATE KEY UPDATE version=VALUES(version),images=VALUES(images),specifications=VALUES(specifications),shipping_note=VALUES(shipping_note),aftercare_note=VALUES(aftercare_note),variant_images=VALUES(variant_images)",
                id,
                current.version() + 1,
                json.writeValueAsString(r.images()),
                json.writeValueAsString(r.specifications()),
                r.shipping_note(),
                r.aftercare_note(),
                json.writeValueAsString(mapping));
        invalidations.presentationChanged(id);
        return product(id, command.merchant_id());
    }

    public Store store(String id, boolean publicRead) {
        storeScope(id, publicRead, false);
        var rows = db.queryForList("SELECT * FROM catalog_store_presentation WHERE store_id=?", id);
        if (rows.isEmpty()) return new Store(id, 0, "", null, "", "");
        var r = rows.getFirst();
        return new Store(
                id,
                ((Number) r.get("version")).longValue(),
                r.get("introduction").toString(),
                (String) r.get("logo_id"),
                r.get("contact_phone").toString(),
                r.get("service_hours").toString());
    }

    @Transactional
    public Store saveStore(StoreCommand command) {
        var r = command.request();
        if (r == null) throw new IllegalArgumentException("请填写店铺资料");
        text(r.introduction(), 500);
        text(r.contact_phone(), 32);
        text(r.service_hours(), 80);
        if (r.logo_id() != null) media(r.logo_id());
        if (!r.contact_phone().isEmpty() && !r.contact_phone().matches("[+0-9() -]{6,32}"))
            throw new IllegalArgumentException("请填写有效的店铺联系电话");
        storeScope(command.merchant_id(), false, true);
        var old = store(command.merchant_id(), false);
        version(old.version(), r.expected_version());
        db.update(
                "INSERT INTO catalog_store_presentation(store_id,version,introduction,logo_id,contact_phone,service_hours) VALUES(?,?,?,?,?,?) ON DUPLICATE KEY UPDATE version=VALUES(version),introduction=VALUES(introduction),logo_id=VALUES(logo_id),contact_phone=VALUES(contact_phone),service_hours=VALUES(service_hours)",
                command.merchant_id(),
                old.version() + 1,
                r.introduction(),
                r.logo_id(),
                r.contact_phone(),
                r.service_hours());
        return store(command.merchant_id(), false);
    }

    public Published published(String id) {
        media(id);
        int count = db.queryForObject(
                "SELECT (SELECT COUNT(*) FROM catalog_product_presentation x JOIN catalog_product p ON p.product_id=x.product_id JOIN catalog_store s ON s.store_id=p.store_id WHERE p.listed=TRUE AND s.enabled=TRUE AND JSON_CONTAINS(x.images,JSON_QUOTE(?)))+(SELECT COUNT(*) FROM catalog_store_presentation x JOIN catalog_store s ON s.store_id=x.store_id WHERE s.enabled=TRUE AND x.logo_id=?)",
                Integer.class,
                id,
                id);
        return new Published(count > 0);
    }
}
