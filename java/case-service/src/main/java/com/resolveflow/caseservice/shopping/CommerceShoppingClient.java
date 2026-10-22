package com.resolveflow.caseservice.shopping;

import com.resolveflow.caseservice.order.CommerceOrderLineClient.CommerceUnavailableException;
import com.resolveflow.shared.error.ApiError;
import com.resolveflow.shared.security.JwtCodec;
import com.resolveflow.shared.security.ServiceScopes;
import com.resolveflow.shared.shopping.CheckoutWire.*;
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
    public com.resolveflow.shared.shopping.ProductReviewWire.Page productReviews(
            String product, Long before, Integer limit) {
        return call(
                rest.get().uri(u -> {
                    var b = u.path("/internal/v1/shop/products/{id}/reviews");
                    if (before != null) b.queryParam("before", before);
                    if (limit != null) b.queryParam("limit", limit);
                    return b.build(product);
                }),
                false,
                new ParameterizedTypeReference<>() {});
    }

    public com.resolveflow.shared.shopping.ProductReviewWire.Own ownReview(
            String line, String merchant, String customer) {
        return call(
                rest.get()
                        .uri(u -> u.path("/internal/v1/shop/orders/lines/{id}/review")
                                .queryParam("merchant_id", merchant)
                                .queryParam("customer_id", customer)
                                .build(line)),
                true,
                new ParameterizedTypeReference<>() {});
    }

    public com.resolveflow.shared.shopping.ProductReviewWire.Review saveReview(
            String line, com.resolveflow.shared.shopping.ProductReviewWire.Command command) {
        return call(
                rest.post()
                        .uri("/internal/v1/shop/orders/lines/{id}/review", line)
                        .body(command),
                true,
                new ParameterizedTypeReference<>() {});
    }

    public com.resolveflow.shared.shopping.ProductReviewWire.Page merchantReviews(
            String merchant, Long before, Integer limit) {
        return call(
                rest.get().uri(u -> {
                    var b = u.path("/internal/v1/merchant/reviews").queryParam("merchant_id", merchant);
                    if (before != null) b.queryParam("before", before);
                    if (limit != null) b.queryParam("limit", limit);
                    return b.build();
                }),
                ServiceScopes.COMMERCE_FULFILLMENT,
                new ParameterizedTypeReference<>() {});
    }

    public com.resolveflow.shared.shopping.ProductReviewWire.Review replyReview(
            long id, com.resolveflow.shared.shopping.ProductReviewWire.ReplyCommand command) {
        return call(
                rest.post().uri("/internal/v1/merchant/reviews/{id}/reply", id).body(command),
                ServiceScopes.COMMERCE_FULFILLMENT,
                new ParameterizedTypeReference<>() {});
    }

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
        return call(request, checkout ? ServiceScopes.COMMERCE_CHECKOUT : ServiceScopes.COMMERCE_READ, type);
    }

    private <T> T call(RestClient.RequestHeadersSpec<?> request, String scope, ParameterizedTypeReference<T> type) {
        try {
            T body = request.header(
                            HttpHeaders.AUTHORIZATION,
                            "Bearer " + codec.issueServiceToken("case-service", null, null, scope, Instant.now()))
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

    public com.resolveflow.shared.shopping.ManagementWire.StoreSync syncStore(
            com.resolveflow.shared.shopping.ManagementWire.StoreSync request) {
        return call(
                rest.post().uri("/internal/v1/catalog-management/stores").body(request),
                ServiceScopes.COMMERCE_CATALOG,
                new ParameterizedTypeReference<>() {});
    }

    public com.resolveflow.shared.shopping.ManagementWire.Products managedProducts(
            String merchant, String after, Integer limit) {
        return call(
                rest.get().uri(u -> {
                    var b = u.path("/internal/v1/catalog-management/products").queryParam("merchant_id", merchant);
                    if (after != null) b.queryParam("after", after);
                    if (limit != null) b.queryParam("limit", limit);
                    return b.build();
                }),
                ServiceScopes.COMMERCE_CATALOG,
                new ParameterizedTypeReference<>() {});
    }

    public com.resolveflow.shared.shopping.ManagementWire.Product managedProduct(String merchant, String id) {
        return call(
                rest.get()
                        .uri(u -> u.path("/internal/v1/catalog-management/products/{id}")
                                .queryParam("merchant_id", merchant)
                                .build(id)),
                ServiceScopes.COMMERCE_CATALOG,
                new ParameterizedTypeReference<>() {});
    }

    public com.resolveflow.shared.shopping.ManagementWire.Product saveProduct(
            String id, com.resolveflow.shared.shopping.ManagementWire.ProductCommand request) {
        return call(
                rest.post()
                        .uri(
                                id == null
                                        ? "/internal/v1/catalog-management/products"
                                        : "/internal/v1/catalog-management/products/" + id)
                        .body(request),
                ServiceScopes.COMMERCE_CATALOG,
                new ParameterizedTypeReference<>() {});
    }

    public com.resolveflow.shared.shopping.FulfillmentWire.Trades merchantOrders(
            String merchant, String status, String cursor, Integer limit) {
        return call(
                rest.get().uri(u -> {
                    var b = u.path("/internal/v1/merchant/orders").queryParam("merchant_id", merchant);
                    if (status != null) b.queryParam("status", status);
                    if (cursor != null) b.queryParam("cursor", cursor);
                    if (limit != null) b.queryParam("limit", limit);
                    return b.build();
                }),
                ServiceScopes.COMMERCE_FULFILLMENT,
                new ParameterizedTypeReference<>() {});
    }

    public com.resolveflow.shared.shopping.FulfillmentWire.Trade merchantOrder(String id, String merchant) {
        return call(
                rest.get()
                        .uri(u -> u.path("/internal/v1/merchant/orders/{id}")
                                .queryParam("merchant_id", merchant)
                                .build(id)),
                ServiceScopes.COMMERCE_FULFILLMENT,
                new ParameterizedTypeReference<>() {});
    }

    public com.resolveflow.shared.shopping.FulfillmentWire.Fulfillment ship(
            String id, com.resolveflow.shared.shopping.FulfillmentWire.ShipCommand command) {
        return call(
                rest.post()
                        .uri("/internal/v1/merchant/orders/{id}/simulated-shipment", id)
                        .body(command),
                ServiceScopes.COMMERCE_FULFILLMENT,
                new ParameterizedTypeReference<>() {});
    }

    public com.resolveflow.shared.shopping.FulfillmentWire.Fulfillment fulfillment(
            String id, String merchant, String customer) {
        return call(
                rest.get()
                        .uri(u -> u.path("/internal/v1/shop/orders/{id}/fulfillment")
                                .queryParam("merchant_id", merchant)
                                .queryParam("customer_id", customer)
                                .build(id)),
                true,
                new ParameterizedTypeReference<>() {});
    }

    public com.resolveflow.shared.shopping.MultiCheckoutWire.Quote cartQuote(
            String store, com.resolveflow.shared.shopping.MultiCheckoutWire.QuoteCommand command) {
        return call(
                rest.post().uri("/internal/v1/shop/cart/{store}/quote", store).body(command),
                true,
                new ParameterizedTypeReference<>() {});
    }

    public Purchase cartDraft(String store, com.resolveflow.shared.shopping.MultiCheckoutWire.Command command) {
        return call(
                rest.post().uri("/internal/v1/shop/cart/{store}/drafts", store).body(command),
                true,
                new ParameterizedTypeReference<>() {});
    }

    public com.resolveflow.shared.shopping.CartWire.Group cart(String store, String customer) {
        return call(
                rest.get()
                        .uri(u -> u.path("/internal/v1/shop/cart/{store}")
                                .queryParam("customer_id", customer)
                                .build(store)),
                true,
                new ParameterizedTypeReference<>() {});
    }

    public com.resolveflow.shared.shopping.CartWire.Receipt cartWrite(
            String store, com.resolveflow.shared.shopping.CartWire.Command command) {
        return call(
                rest.post().uri("/internal/v1/shop/cart/{store}/items", store).body(command),
                true,
                new ParameterizedTypeReference<>() {});
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

    public Payment pay(String id, PayCommand command) {
        return call(
                rest.post().uri("/internal/v1/shop/drafts/{id}/payment", id).body(command),
                true,
                new ParameterizedTypeReference<>() {});
    }

    public Lookup payment(String id, String merchant, String customer) {
        return call(
                rest.get()
                        .uri(u -> u.path("/internal/v1/shop/drafts/{id}/payment")
                                .queryParam("merchant_id", merchant)
                                .queryParam("customer_id", customer)
                                .build(id)),
                true,
                new ParameterizedTypeReference<>() {});
    }

    public Draft cancel(String id, ScopeCommand command) {
        return call(
                rest.post().uri("/internal/v1/shop/drafts/{id}/cancel", id).body(command),
                true,
                new ParameterizedTypeReference<>() {});
    }

    public Purchase purchase(String id, String merchant, String customer) {
        return call(
                rest.get()
                        .uri(u -> u.path("/internal/v1/shop/purchases/{id}")
                                .queryParam("merchant_id", merchant)
                                .queryParam("customer_id", customer)
                                .build(id)),
                true,
                new ParameterizedTypeReference<>() {});
    }

    public Purchases purchases(String merchant, String customer, String status, String cursor, int limit) {
        return call(
                rest.get().uri(u -> {
                    var b = u.path("/internal/v1/shop/purchases")
                            .queryParam("merchant_id", merchant)
                            .queryParam("customer_id", customer)
                            .queryParam("limit", limit);
                    if (status != null) b.queryParam("status", status);
                    if (cursor != null) b.queryParam("cursor", cursor);
                    return b.build();
                }),
                true,
                new ParameterizedTypeReference<>() {});
    }
}
