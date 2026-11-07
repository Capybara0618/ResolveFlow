package com.resolveflow.commerce.security;

import com.resolveflow.shared.error.ApiError;
import com.resolveflow.shared.security.IdentityAccessWire.*;
import com.resolveflow.shared.security.JwtCodec;
import com.resolveflow.shared.security.Role;
import com.resolveflow.shared.security.ServiceScopes;
import com.resolveflow.shared.shopping.ShippingWire;
import java.time.Clock;
import java.time.Duration;
import java.time.Instant;
import java.util.HashSet;
import java.util.List;
import java.util.Objects;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.http.client.JdkClientHttpRequestFactory;
import org.springframework.stereotype.Component;
import org.springframework.web.client.RestClient;
import tools.jackson.databind.ObjectMapper;

/** Current-session checks are remote and fail closed; resource ownership stays in Commerce. */
@Component
public class IdentityAccessClient {
    private final RestClient rest;
    private final JwtCodec codec;
    private final Clock clock;

    public IdentityAccessClient(
            RestClient.Builder builder,
            JwtCodec codec,
            Clock clock,
            @Value("${resolveflow.identity.base-url:http://127.0.0.1:8083}") String base) {
        var transport = new JdkClientHttpRequestFactory(java.net.http.HttpClient.newBuilder()
                .connectTimeout(Duration.ofSeconds(1))
                .build());
        transport.setReadTimeout(Duration.ofSeconds(3));
        rest = builder.clone().requestFactory(transport).baseUrl(base).build();
        this.codec = codec;
        this.clock = clock;
    }

    public Context resolve(String authorization) {
        return resolve(authorization, null);
    }

    public Context resolve(String authorization, ShippingWire.Selection shipping) {
        var now = Instant.now(clock);
        com.resolveflow.shared.security.AuthenticatedPrincipal local;
        long version;
        try {
            if (authorization == null || authorization.length() > 8192)
                throw new JwtCodec.TokenException("user token required");
            local = codec.principalFromAuthorizationHeader(authorization, now);
            version = codec.identityVersionFromAuthorizationHeader(authorization, now);
        } catch (JwtCodec.TokenException e) {
            throw new Refused(401, "UNAUTHENTICATED", "登录已失效，请重新登录");
        }
        if (local.role() == Role.PLATFORM_ADMIN) throw new Refused(403, "FORBIDDEN_SCOPE", "平台管理员无交易权限");
        try {
            var context = rest.post()
                    .uri("/internal/v1/identity/resolve")
                    .header(
                            "Authorization",
                            "Bearer "
                                    + codec.issueServiceToken(
                                            "commerce-service", null, null, ServiceScopes.IDENTITY_RESOLVE, now))
                    .body(new Resolve(authorization, shipping))
                    .retrieve()
                    .onStatus(s -> s.isError(), (request, response) -> {
                        int status = response.getStatusCode().value();
                        if (!List.of(400, 401, 403, 404, 409).contains(status)) throw unavailable();
                        var error = new ObjectMapper().readValue(response.getBody(), ApiError.class);
                        throw new Refused(status, error.code(), error.message());
                    })
                    .body(Context.class);
            if (context == null
                    || !local.equals(context.principal())
                    || version != context.identity_version()
                    || context.bindings() == null
                    || context.bindings().size() > 20
                    || !local.isPlatformBuyer() && !context.bindings().isEmpty()) throw unavailable();
            var merchants = new HashSet<String>();
            for (var binding : context.bindings()) {
                if (binding == null
                        || binding.merchantId() == null
                        || binding.merchantId().isBlank()
                        || binding.buyerId() == null
                        || !Objects.equals(binding.buyerId(), local.buyerId())
                        || !merchants.add(binding.merchantId())) throw unavailable();
            }
            if (shipping != null
                    && (context.shipping() == null
                            || !Objects.equals(
                                    shipping.address_id(), context.shipping().address_id())
                            || !Objects.equals(
                                    shipping.expected_version(),
                                    context.shipping().version()))) throw unavailable();
            return context;
        } catch (Refused e) {
            throw e;
        } catch (RuntimeException e) {
            throw unavailable();
        }
    }

    private static Refused unavailable() {
        return new Refused(503, "UPSTREAM_UNAVAILABLE", "身份服务暂时不可用，请稍后重试");
    }

    public static class Refused extends RuntimeException {
        public final int status;
        public final String code;

        public Refused(int status, String code, String message) {
            super(message);
            this.status = status;
            this.code = code;
        }
    }
}
