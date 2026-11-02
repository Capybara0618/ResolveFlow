package com.resolveflow.commerce.publicapi;

import com.resolveflow.commerce.catalog.ShoppingService.Refused;
import com.resolveflow.commerce.security.IdentityAccessClient;
import com.resolveflow.shared.security.*;
import com.resolveflow.shared.security.IdentityAccessWire.*;
import com.resolveflow.shared.shopping.ShippingWire;
import java.util.function.Function;
import org.springframework.stereotype.Component;

/** Authentication is remote; every resource lookup still carries a trusted local scope. */
@Component
public class CommerceAccess {
    private final IdentityAccessClient identity;

    public CommerceAccess(IdentityAccessClient identity) {
        this.identity = identity;
    }

    public Context buyer(String auth) {
        var context = identity.resolve(auth);
        if (!context.principal().isPlatformBuyer()) throw new Refused(403, "FORBIDDEN_SCOPE", "请使用平台买家账号操作本人交易");
        return context;
    }

    public AuthenticatedPrincipal merchant(String auth) {
        var p = identity.resolve(auth).principal();
        if (p.role() != Role.MERCHANT_ADMIN) throw new Refused(403, "FORBIDDEN_SCOPE", "请使用本店商家账号");
        return p;
    }

    public ShippingWire.Snapshot shipping(String auth, ShippingWire.Selection choice) {
        return identity.resolve(auth, choice).shipping();
    }

    public static String key(String key) {
        if (key == null || !key.matches("[A-Za-z0-9_-]{1,128}"))
            throw new Refused(400, "INVALID_ARGUMENT", "需要有效的请求标识");
        return key;
    }

    public static Binding binding(Context actor, String store) {
        return actor.bindings().stream()
                .filter(s -> s.merchantId().equals(store))
                .findFirst()
                .orElseThrow(CommerceAccess::missing);
    }

    public static <T> T owned(Context actor, Function<Binding, T> read) {
        for (var binding : actor.bindings()) {
            try {
                return read.apply(binding);
            } catch (Refused e) {
                if (e.status != 404) throw e;
            }
        }
        throw missing();
    }

    public static Refused missing() {
        return new Refused(404, "NOT_FOUND", "商品或订单不存在");
    }
}
