package com.resolveflow.caseservice.auth;

import com.resolveflow.caseservice.order.RequestPrincipalResolver.Session;
import com.resolveflow.caseservice.shopping.CommerceShoppingClient.Refused;
import java.time.LocalDate;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.UUID;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Service;
import org.springframework.transaction.support.TransactionTemplate;

@Service
public class AccountService {
    public record Profile(
            String username,
            String display_name,
            String avatar_id,
            long version,
            String login_name,
            String phone,
            String gender,
            LocalDate birth_date) {}

    public record EditProfile(
            String display_name, Long expected_version, String phone, String gender, LocalDate birth_date) {
        public EditProfile(String display_name, Long expected_version) {
            this(display_name, expected_version, null, null, null);
        }
    }

    public record Address(
            String address_id,
            String recipient,
            String phone,
            String province,
            String city,
            String district,
            String detail,
            boolean is_default,
            long version) {}

    public record EditAddress(
            String recipient,
            String phone,
            String province,
            String city,
            String district,
            String detail,
            Boolean is_default,
            Long expected_version) {}

    private final JdbcTemplate db;
    private final TransactionTemplate tx;
    private final AvatarStore avatars;

    public AccountService(
            JdbcTemplate db, org.springframework.transaction.PlatformTransactionManager manager, AvatarStore avatars) {
        this.db = db;
        this.tx = new TransactionTemplate(manager);
        this.avatars = avatars;
    }

    private Map<String, Object> lock(Session s) {
        var rows = db.queryForList(
                "SELECT username,profile_version,avatar_id FROM identity_account WHERE username=? AND enabled=TRUE AND identity_version=? FOR UPDATE",
                s.principal().subject(),
                s.identityVersion());
        if (rows.isEmpty()) throw new Refused(401, "UNAUTHENTICATED", "登录已失效，请重新登录");
        return rows.getFirst();
    }

    private static void version(long current, Long expected) {
        if (expected == null || expected < 1) throw invalid("请提供当前版本");
        if (current != expected) throw new Refused(409, "VERSION_CONFLICT", "内容已变化，请刷新后再保存");
    }

    private static String text(String v, int max, String label) {
        if (v == null || v.isBlank() || v.trim().length() > max || v.chars().anyMatch(Character::isISOControl))
            throw invalid("请填写有效的" + label);
        return v.trim();
    }

    private static Refused invalid(String message) {
        return new Refused(400, "INVALID_ARGUMENT", message);
    }

    private static Refused missing() {
        return new Refused(404, "NOT_FOUND", "地址不存在");
    }

    private static String buyer(Session s) {
        if (!s.principal().isPlatformBuyer()) throw new Refused(403, "FORBIDDEN_SCOPE", "请使用买家账号管理地址");
        return s.principal().buyerId();
    }

    public Profile profile(Session s) {
        var values = db.query(
                "SELECT username,display_name,avatar_id,profile_version,login_key,phone,gender,birth_date FROM identity_account WHERE username=?",
                (r, n) -> new Profile(
                        r.getString(1),
                        r.getString(2),
                        r.getString(3),
                        r.getLong(4),
                        r.getString(5),
                        r.getString(6),
                        r.getString(7),
                        r.getObject(8, LocalDate.class)),
                s.principal().subject());
        if (values.isEmpty()) throw new Refused(404, "NOT_FOUND", "账号不存在");
        return values.getFirst();
    }

    public Profile edit(Session s, EditProfile body) {
        String name = text(body.display_name(), 120, "昵称");
        String phone = body.phone() == null || body.phone().isBlank()
                ? null
                : body.phone().trim();
        if (phone != null && !phone.matches("[+0-9() -]{6,32}")) throw invalid("请填写有效联系电话");
        if (body.gender() != null
                && !Set.of("UNDISCLOSED", "FEMALE", "MALE", "OTHER").contains(body.gender())) throw invalid("请选择有效性别");
        if (body.birth_date() != null
                && (body.birth_date().isBefore(LocalDate.of(1900, 1, 1))
                        || body.birth_date().isAfter(LocalDate.now()))) throw invalid("请填写有效生日");
        return tx.execute(st -> {
            var row = lock(s);
            version(((Number) row.get("profile_version")).longValue(), body.expected_version());
            db.update(
                    "UPDATE identity_account SET display_name=?,phone=?,gender=?,birth_date=?,profile_version=profile_version+1,account_version=account_version+1 WHERE username=?",
                    name,
                    phone,
                    body.gender(),
                    body.birth_date(),
                    s.principal().subject());
            return profile(s);
        });
    }

    public Profile upload(Session s, Long expected, byte[] bytes) {
        String id = avatars.save(bytes);
        try {
            return tx.execute(st -> {
                var row = lock(s);
                version(((Number) row.get("profile_version")).longValue(), expected);
                db.update(
                        "UPDATE identity_account SET avatar_id=?,profile_version=profile_version+1 WHERE username=?",
                        id,
                        s.principal().subject());
                return profile(s);
            });
        } catch (RuntimeException e) {
            avatars.discard(id);
            throw e;
        }
    }

    public Profile resetAvatar(Session s, Long expected) {
        return tx.execute(st -> {
            var row = lock(s);
            version(((Number) row.get("profile_version")).longValue(), expected);
            db.update(
                    "UPDATE identity_account SET avatar_id=NULL,profile_version=profile_version+1 WHERE username=?",
                    s.principal().subject());
            return profile(s);
        });
    }

    public byte[] avatar(Session s) {
        String id = profile(s).avatar_id();
        if (id == null) throw new Refused(404, "NOT_FOUND", "尚未设置头像");
        return avatars.read(id);
    }

    public List<Address> addresses(Session s) {
        return db.query(
                "SELECT * FROM buyer_address WHERE buyer_id=? AND deleted=FALSE ORDER BY is_default DESC,created_at,address_id",
                (r, n) -> new Address(
                        r.getString("address_id"),
                        r.getString("recipient"),
                        r.getString("phone"),
                        r.getString("province"),
                        r.getString("city"),
                        r.getString("district"),
                        r.getString("detail"),
                        r.getBoolean("is_default"),
                        r.getLong("version")),
                buyer(s));
    }

    public Address address(Session s, String id) {
        return addresses(s).stream()
                .filter(a -> a.address_id().equals(id))
                .findFirst()
                .orElseThrow(AccountService::missing);
    }

    public com.resolveflow.shared.shopping.ShippingWire.Snapshot shipping(
            Session s, com.resolveflow.shared.shopping.ShippingWire.Selection choice) {
        if (choice == null || choice.address_id() == null || choice.expected_version() == null)
            throw invalid("请选择收货地址");
        return tx.execute(st -> {
            lock(s);
            var a = address(s, choice.address_id());
            version(a.version(), choice.expected_version());
            return new com.resolveflow.shared.shopping.ShippingWire.Snapshot(
                    a.address_id(),
                    a.version(),
                    a.recipient(),
                    a.phone(),
                    a.province(),
                    a.city(),
                    a.district(),
                    a.detail());
        });
    }

    public Address saveAddress(Session s, String id, EditAddress b) {
        String owner = buyer(s);
        String recipient = text(b.recipient(), 80, "收货人"),
                phone = text(b.phone(), 32, "联系电话"),
                province = text(b.province(), 80, "省份"),
                city = text(b.city(), 80, "城市"),
                district = text(b.district(), 80, "区县"),
                detail = text(b.detail(), 300, "详细地址");
        if (!phone.matches("[+0-9() -]{6,32}")) throw invalid("请填写有效的联系电话");
        return tx.execute(st -> {
            lock(s);
            var existing = addresses(s);
            boolean creating = id == null;
            if (creating && existing.size() >= 20) throw invalid("最多保存20个收货地址");
            Address old = creating
                    ? null
                    : existing.stream()
                            .filter(a -> a.address_id().equals(id))
                            .findFirst()
                            .orElseThrow(AccountService::missing);
            if (old != null) version(old.version(), b.expected_version());
            boolean makeDefault =
                    existing.isEmpty() || Boolean.TRUE.equals(b.is_default()) || old != null && old.is_default();
            if (makeDefault)
                db.update(
                        "UPDATE buyer_address SET is_default=FALSE,version=version+1 WHERE buyer_id=? AND deleted=FALSE AND is_default=TRUE AND address_id<>?",
                        owner,
                        creating ? "" : id);
            String target = creating ? UUID.randomUUID().toString() : id;
            if (creating)
                db.update(
                        "INSERT INTO buyer_address(address_id,buyer_id,recipient,phone,province,city,district,detail,is_default) VALUES(?,?,?,?,?,?,?,?,?)",
                        target,
                        owner,
                        recipient,
                        phone,
                        province,
                        city,
                        district,
                        detail,
                        makeDefault);
            else
                db.update(
                        "UPDATE buyer_address SET recipient=?,phone=?,province=?,city=?,district=?,detail=?,is_default=?,version=version+1 WHERE address_id=? AND buyer_id=?",
                        recipient,
                        phone,
                        province,
                        city,
                        district,
                        detail,
                        makeDefault,
                        target,
                        owner);
            return address(s, target);
        });
    }

    public void deleteAddress(Session s, String id, Long expected) {
        String owner = buyer(s);
        tx.executeWithoutResult(st -> {
            lock(s);
            var old = address(s, id);
            version(old.version(), expected);
            db.update(
                    "UPDATE buyer_address SET deleted=TRUE,is_default=FALSE,version=version+1 WHERE address_id=? AND buyer_id=?",
                    id,
                    owner);
            if (old.is_default()) {
                var remaining = addresses(s);
                if (!remaining.isEmpty())
                    db.update(
                            "UPDATE buyer_address SET is_default=TRUE,version=version+1 WHERE address_id=?",
                            remaining.getFirst().address_id());
            }
        });
    }
}
