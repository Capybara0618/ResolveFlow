package com.resolveflow.gateway.security;

import static org.assertj.core.api.Assertions.assertThat;

import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.springframework.http.HttpHeaders;
import org.springframework.mock.http.server.reactive.MockServerHttpRequest;
import org.springframework.mock.web.server.MockServerWebExchange;
import org.springframework.web.server.ServerWebExchange;
import org.springframework.web.server.WebFilterChain;
import reactor.core.publisher.Mono;

/**
 * The gateway must not forward a client-supplied identity.
 *
 * <p>Tested at the filter level rather than through a route: the gateway has no routes yet
 * (they arrive with the first proxied surface), and a rule that only holds once a route exists is
 * exactly the kind of claim this project tries not to make.
 */
class IdentityHeaderStripFilterTest {

    private final IdentityHeaderStripFilter filter = new IdentityHeaderStripFilter();

    private ServerWebExchange exchangeAfterFilter(HttpHeaders incoming) {
        MockServerWebExchange exchange = MockServerWebExchange.from(
                MockServerHttpRequest.get("/api/v1/orders").headers(incoming).build());
        ServerWebExchange[] seen = new ServerWebExchange[1];
        WebFilterChain chain = filtered -> {
            seen[0] = filtered;
            return Mono.empty();
        };
        filter.filter(exchange, chain).block();
        return seen[0];
    }

    @Test
    @DisplayName("identity headers do not reach the rest of the chain")
    void identityHeadersAreRemoved() {
        HttpHeaders headers = new HttpHeaders();
        headers.add("X-User", "someone-else");
        headers.add("X-Role", "OPERATOR");
        headers.add("X-Merchant", "M-1002");
        headers.add("X-Customer", "C-2004");

        ServerWebExchange filtered = exchangeAfterFilter(headers);

        for (String name : IdentityHeaderStripFilter.IDENTITY_HEADERS) {
            assertThat(filtered.getRequest().getHeaders().getFirst(name))
                    .as("%s must not survive the gateway", name)
                    .isNull();
        }
    }

    @Test
    @DisplayName("everything else the protocol needs is left alone")
    void otherHeadersSurvive() {
        HttpHeaders headers = new HttpHeaders();
        headers.add("Authorization", "Bearer eyJhbGciOiJIUzI1NiJ9.demo.token");
        headers.add("Idempotency-Key", "3f1c0a9e-8a2f-4c2f-9a3e-6f0d0b7c1234");
        headers.add("traceparent", "00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01");

        ServerWebExchange filtered = exchangeAfterFilter(headers);

        assertThat(filtered.getRequest().getHeaders().getFirst("Authorization")).startsWith("Bearer ");
        assertThat(filtered.getRequest().getHeaders().getFirst("Idempotency-Key"))
                .isNotBlank();
        assertThat(filtered.getRequest().getHeaders().getFirst("traceparent")).isNotBlank();
    }

    @Test
    @DisplayName("a request with no identity headers is untouched")
    void harmlessRequestPassesThrough() {
        ServerWebExchange filtered = exchangeAfterFilter(new HttpHeaders());

        assertThat(filtered.getRequest().getURI().getPath()).isEqualTo("/api/v1/orders");
        assertThat(filtered.getRequest().getMethod().name()).isEqualTo("GET");
    }
}
