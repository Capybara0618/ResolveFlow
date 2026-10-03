package com.resolveflow.caseservice.shopping;

import com.resolveflow.caseservice.order.CommerceOrderLineClient.CommerceUnavailableException;
import com.resolveflow.shared.error.ApiError;
import com.resolveflow.shared.security.JwtCodec;
import com.resolveflow.shared.security.ServiceScopes;
import com.resolveflow.shared.shopping.ShoppingWire.*;
import java.time.Instant;
import java.util.List;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.core.ParameterizedTypeReference;
import org.springframework.http.HttpHeaders;
import org.springframework.stereotype.Component;
import org.springframework.web.client.RestClient;
import tools.jackson.databind.ObjectMapper;

@Component
public class CommerceShoppingClient {
    private final RestClient rest;
    private final JwtCodec codec;

    public CommerceShoppingClient(
            RestClient.Builder builder, JwtCodec codec, @Value("${resolveflow.commerce.base-url}") String base) {
        this.rest = builder.baseUrl(base).build();
        this.codec = codec;
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

    private <T> T call(RestClient.RequestHeadersSpec<?> request, boolean checkout, ParameterizedTypeReference<T> type) {
        try {
            T body = request.header(
                            HttpHeaders.AUTHORIZATION,
                            "Bearer "
                                    + codec.issueServiceToken(
                                            "case-service",
                                            null,
                                            null,
                                            checkout ? ServiceScopes.COMMERCE_CHECKOUT : ServiceScopes.COMMERCE_READ,
                                            Instant.now()))
                    .retrieve()
                    .onStatus(s -> s.is4xxClientError(), (req, res) -> {
                        int status = res.getStatusCode().value();
                        if (!List.of(400, 404, 409).contains(status))
                            throw new CommerceUnavailableException("shopping service refused facade credentials", null);
                        ApiError error = new ObjectMapper().readValue(res.getBody(), ApiError.class);
                        throw new Refused(status, error.code(), error.message());
                    })
                    .body(type);
            if (body == null) throw new CommerceUnavailableException("shopping returned an empty body", null);
            return body;
        } catch (Refused error) {
            throw error;
        } catch (RuntimeException error) {
            throw new CommerceUnavailableException("shopping service is temporarily unavailable", error);
        }
    }

    public List<Store> stores() {
        return call(rest.get().uri("/internal/v1/shop/stores"), false, new ParameterizedTypeReference<>() {});
    }

    public Store store(String id) {
        return call(rest.get().uri("/internal/v1/shop/stores/{id}", id), false, new ParameterizedTypeReference<>() {});
    }

    public Product product(String id) {
        return call(
                rest.get().uri("/internal/v1/shop/products/{id}", id), false, new ParameterizedTypeReference<>() {});
    }

    public Products products(String query, String category, String store, String after, Integer limit) {
        return call(
                rest.get().uri(u -> {
                    var b = u.path("/internal/v1/shop/products");
                    if (query != null) b.queryParam("query", query);
                    if (category != null) b.queryParam("category", category);
                    if (store != null) b.queryParam("store_id", store);
                    if (after != null) b.queryParam("after", after);
                    if (limit != null) b.queryParam("limit", limit);
                    return b.build();
                }),
                false,
                new ParameterizedTypeReference<>() {});
    }

    public Quote quote(QuoteRequest request) {
        return call(
                rest.post().uri("/internal/v1/shop/quote").body(request), false, new ParameterizedTypeReference<>() {});
    }

    public Draft create(DraftCommand command) {
        return call(
                rest.post().uri("/internal/v1/shop/drafts").body(command), true, new ParameterizedTypeReference<>() {});
    }

    public Draft read(String id, String merchant, String customer) {
        return call(
                rest.get()
                        .uri(u -> u.path("/internal/v1/shop/drafts/{id}")
                                .queryParam("merchant_id", merchant)
                                .queryParam("customer_id", customer)
                                .build(id)),
                true,
                new ParameterizedTypeReference<>() {});
    }
}
