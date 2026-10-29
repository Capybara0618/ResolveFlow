package com.resolveflow.caseservice.shopping;

import com.resolveflow.caseservice.auth.AvatarStore;
import com.resolveflow.caseservice.order.RequestPrincipalResolver;
import com.resolveflow.caseservice.order.RequestPrincipalResolver.Session;
import com.resolveflow.shared.error.ApiError;
import com.resolveflow.shared.security.Role;
import com.resolveflow.shared.shopping.PresentationWire.*;
import java.util.*;
import org.springframework.http.ResponseEntity;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.transaction.PlatformTransactionManager;
import org.springframework.transaction.support.TransactionTemplate;
import org.springframework.web.bind.annotation.*;
import org.springframework.web.multipart.MultipartFile;

/** Public catalog media never grants access to private account avatar IDs. */
@RestController
public class PresentationController {
    private final CommerceShoppingClient commerce;
    private final RequestPrincipalResolver principals;
    private final JdbcTemplate db;
    private final AvatarStore files;
    private final TransactionTemplate tx;

    public PresentationController(
            CommerceShoppingClient commerce,
            RequestPrincipalResolver principals,
            JdbcTemplate db,
            AvatarStore files,
            PlatformTransactionManager manager) {
        this.commerce = commerce;
        this.principals = principals;
        this.db = db;
        this.files = files;
        tx = new TransactionTemplate(manager);
    }

    private Session merchant(String auth) {
        var s = principals.session(auth);
        if (s.principal().role() != Role.MERCHANT_ADMIN)
            throw new CommerceShoppingClient.Refused(403, "FORBIDDEN_SCOPE", "请使用本店商家账号");
        return s;
    }

    private void media(Session s, String id) {
        if (id == null) return;
        if (db.queryForObject(
                        "SELECT COUNT(*) FROM catalog_media WHERE media_id=? AND merchant_id=?",
                        Integer.class,
                        id,
                        s.principal().merchantId())
                != 1) throw new CommerceShoppingClient.Refused(404, "NOT_FOUND", "本店图片不存在");
    }

    @GetMapping("/api/v1/shop/products/{id}/presentation")
    public Product product(@PathVariable String id) {
        return commerce.presentationProduct(id, null);
    }

    @GetMapping("/api/v1/shop/stores/{id}/presentation")
    public Store store(@PathVariable String id) {
        return commerce.presentationStore(id, false);
    }

    @GetMapping("/api/v1/merchant/products/{id}/presentation")
    public Product managed(
            @RequestHeader(name = "Authorization", required = false) String auth, @PathVariable String id) {
        return commerce.presentationProduct(id, merchant(auth).principal().merchantId());
    }

    @PostMapping("/api/v1/merchant/products/{id}/presentation")
    public Product save(
            @RequestHeader(name = "Authorization", required = false) String auth,
            @PathVariable String id,
            @RequestBody ProductWrite r) {
        var s = merchant(auth);
        if (r.images() == null || r.images().size() > 8)
            throw new CommerceShoppingClient.Refused(400, "INVALID_ARGUMENT", "最多8张商品图片");
        for (String image : r.images()) {
            if (image == null) throw new CommerceShoppingClient.Refused(400, "INVALID_ARGUMENT", "图片标识无效");
            media(s, image);
        }
        return commerce.savePresentation(
                id, new ProductCommand(s.principal().merchantId(), s.principal().subject(), r));
    }

    @GetMapping("/api/v1/merchant/store/presentation")
    public Store managedStore(@RequestHeader(name = "Authorization", required = false) String auth) {
        return commerce.presentationStore(merchant(auth).principal().merchantId(), true);
    }

    @PostMapping("/api/v1/merchant/store/presentation")
    public Store saveStore(
            @RequestHeader(name = "Authorization", required = false) String auth, @RequestBody StoreWrite r) {
        var s = merchant(auth);
        media(s, r.logo_id());
        return commerce.saveStorePresentation(
                new StoreCommand(s.principal().merchantId(), s.principal().subject(), r));
    }

    @PostMapping(value = "/api/v1/merchant/media", consumes = "multipart/form-data")
    public Media upload(
            @RequestHeader(name = "Authorization", required = false) String auth, @RequestParam MultipartFile file)
            throws java.io.IOException {
        var s = merchant(auth);
        if (file.getSize() > 2 * 1024 * 1024)
            throw new CommerceShoppingClient.Refused(400, "INVALID_IMAGE", "请选择2MB以内的PNG或JPEG图片");
        String id = files.saveCatalog(file.getBytes());
        try {
            return tx.execute(st -> {
                var current = db.queryForList(
                        "SELECT username FROM identity_account WHERE username=? AND merchant_id=? AND enabled=TRUE AND identity_version=? FOR UPDATE",
                        String.class,
                        s.principal().subject(),
                        s.principal().merchantId(),
                        s.identityVersion());
                if (current.isEmpty()) throw new CommerceShoppingClient.Refused(401, "UNAUTHENTICATED", "登录已失效，请重新登录");
                if (db.queryForObject(
                                "SELECT COUNT(*) FROM catalog_media WHERE merchant_id=?",
                                Integer.class,
                                s.principal().merchantId())
                        >= 1000) throw new CommerceShoppingClient.Refused(409, "MEDIA_LIMIT", "图片数量已达上限，请联系管理员整理");
                db.update(
                        "INSERT INTO catalog_media(media_id,merchant_id) VALUES(?,?)",
                        id,
                        s.principal().merchantId());
                return new Media(id);
            });
        } catch (RuntimeException e) {
            files.discard(id);
            throw e;
        }
    }

    @GetMapping(value = "/api/v1/merchant/media/{id}", produces = "image/png")
    public ResponseEntity<byte[]> preview(
            @RequestHeader(name = "Authorization", required = false) String auth, @PathVariable String id) {
        media(merchant(auth), id);
        return image(id);
    }

    @GetMapping(value = "/api/v1/shop/media/{id}", produces = "image/png")
    public ResponseEntity<byte[]> published(@PathVariable String id) {
        if (db.queryForObject("SELECT COUNT(*) FROM catalog_media WHERE media_id=?", Integer.class, id) != 1
                || !commerce.publishedMedia(id).published())
            throw new CommerceShoppingClient.Refused(404, "NOT_FOUND", "图片未发布");
        return image(id);
    }

    private ResponseEntity<byte[]> image(String id) {
        return ResponseEntity.ok()
                .header("Cache-Control", "no-store")
                .header("X-Content-Type-Options", "nosniff")
                .body(files.read(id));
    }

    @ExceptionHandler(CommerceShoppingClient.Refused.class)
    public ResponseEntity<ApiError> refused(CommerceShoppingClient.Refused e) {
        return ResponseEntity.status(e.status)
                .body(ApiError.of(
                        e.code, e.getMessage(), false, UUID.randomUUID().toString()));
    }
}
