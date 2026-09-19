package com.resolveflow.gateway.security;

import java.util.List;
import org.springframework.core.Ordered;
import org.springframework.core.annotation.Order;
import org.springframework.http.server.reactive.ServerHttpRequest;
import org.springframework.stereotype.Component;
import org.springframework.web.server.ServerWebExchange;
import org.springframework.web.server.WebFilter;
import org.springframework.web.server.WebFilterChain;
import reactor.core.publisher.Mono;

/**
 * Removes the identity headers a client could otherwise use to name itself.
 *
 * <p>The core contract says the user token carries the principal and that {@code X-User},
 * {@code X-Role} and {@code X-Merchant} "are stripped at the gateway and never trusted here"
 * (contracts/core/openapi-case.yaml, securitySchemes.bearerAuth, citing docs/core-contracts.md:15).
 * This filter is the gateway half of that sentence: a request arriving from the public network cannot
 * pass an identity through a header, whichever route it eventually takes.
 *
 * <p>Stripping (rather than rejecting) is deliberate: the headers are not part of the protocol, so
 * their presence is noise from a proxy or a client library, not a request to be argued with. A
 * service that reads them anyway would still be wrong — case-service's login test proves a forged
 * header changes nothing — so this is hygiene, not the security boundary.
 */
@Component
@Order(Ordered.HIGHEST_PRECEDENCE)
public class IdentityHeaderStripFilter implements WebFilter {

    /** Header names that name a principal and must never come from the client. */
    public static final List<String> IDENTITY_HEADERS = List.of("X-User", "X-Role", "X-Merchant", "X-Customer");

    @Override
    public Mono<Void> filter(ServerWebExchange exchange, WebFilterChain chain) {
        ServerHttpRequest sanitized = exchange.getRequest()
                .mutate()
                .headers(headers -> IDENTITY_HEADERS.forEach(headers::remove))
                .build();
        return chain.filter(exchange.mutate().request(sanitized).build());
    }
}
