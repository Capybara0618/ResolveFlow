package com.resolveflow.gateway;

import org.springframework.beans.factory.annotation.Value;
import org.springframework.cloud.gateway.route.RouteLocator;
import org.springframework.cloud.gateway.route.builder.RouteLocatorBuilder;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.http.HttpMethod;

/** Public commerce routes are explicit; private and aftercare routes retain their own bearer checks. */
@Configuration
public class CoreRoutes {

    @Bean
    RouteLocator coreApiRoutes(
            RouteLocatorBuilder builder,
            @Value("${resolveflow.case.base-url:http://127.0.0.1:8083}") String caseBaseUrl,
            @Value("${resolveflow.commerce.base-url:http://127.0.0.1:8081}") String commerceBaseUrl,
            @Value("${resolveflow.commerce.catalog-url:}") String catalogUrl) {
        return builder.routes()
                .route("commerce-public-catalog", route -> {
                    var catalog = route.method(HttpMethod.GET)
                            .and()
                            .path(
                                    "/api/v1/shop/stores",
                                    "/api/v1/shop/stores/{id}",
                                    "/api/v1/shop/products",
                                    "/api/v1/shop/products/{id}",
                                    "/api/v1/shop/products/{id}/presentation",
                                    "/api/v1/shop/stores/{id}/presentation",
                                    "/api/v1/shop/products/{id}/reviews");
                    if (catalogUrl.isBlank()) return catalog.uri(commerceBaseUrl);
                    return catalog.metadata("connect-timeout", 800)
                            .metadata("response-timeout", 2000)
                            .uri(catalogUrl);
                })
                .route(
                        "commerce-public-quote",
                        route -> route.method(HttpMethod.POST)
                                .and()
                                .path("/api/v1/shop/quote")
                                .uri(commerceBaseUrl))
                .route(
                        "commerce-shopping-read",
                        route -> route.method(HttpMethod.GET)
                                .and()
                                .path(
                                        "/api/v1/shop/cart",
                                        "/api/v1/shop/drafts/{id}",
                                        "/api/v1/shop/drafts/{id}/payment",
                                        "/api/v1/shop/purchases",
                                        "/api/v1/shop/purchases/{id}",
                                        "/api/v1/shop/purchases/{id}/shipping")
                                .uri(commerceBaseUrl))
                .route(
                        "commerce-shopping-write",
                        route -> route.method(HttpMethod.POST)
                                .and()
                                .path(
                                        "/api/v1/shop/drafts",
                                        "/api/v1/shop/drafts/{id}/payment",
                                        "/api/v1/shop/drafts/{id}/cancel",
                                        "/api/v1/shop/cart/{store}/items",
                                        "/api/v1/shop/cart/{store}/quote",
                                        "/api/v1/shop/cart/{store}/drafts")
                                .uri(commerceBaseUrl))
                .route(
                        "commerce-merchant-read",
                        route -> route.method(HttpMethod.GET)
                                .and()
                                .path(
                                        "/api/v1/merchant/orders",
                                        "/api/v1/merchant/orders/{id}",
                                        "/api/v1/merchant/orders/{id}/shipping",
                                        "/api/v1/shop/purchases/{id}/fulfillment",
                                        "/api/v1/shop/orders/lines/{id}/review",
                                        "/api/v1/merchant/reviews",
                                        "/api/v1/merchant/products",
                                        "/api/v1/merchant/products/{id}")
                                .uri(commerceBaseUrl))
                .route(
                        "commerce-merchant-write",
                        route -> route.method(HttpMethod.POST)
                                .and()
                                .path(
                                        "/api/v1/merchant/orders/{id}/simulated-shipment",
                                        "/api/v1/shop/orders/lines/{id}/review",
                                        "/api/v1/merchant/reviews/{id}/reply",
                                        "/api/v1/merchant/products",
                                        "/api/v1/merchant/products/{id}")
                                .uri(commerceBaseUrl))
                .route(
                        "commerce-orders",
                        route -> route.method(HttpMethod.GET)
                                .and()
                                .path("/api/v1/orders", "/api/v1/orders/{id}", "/api/v1/orders/lines/{id}")
                                .uri(commerceBaseUrl))
                .route("case-core-api", route -> route.path("/api/v1/**").uri(caseBaseUrl))
                .build();
    }
}
