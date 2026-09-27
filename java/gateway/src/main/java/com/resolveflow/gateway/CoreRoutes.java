package com.resolveflow.gateway;

import org.springframework.beans.factory.annotation.Value;
import org.springframework.cloud.gateway.route.RouteLocator;
import org.springframework.cloud.gateway.route.builder.RouteLocatorBuilder;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;

/** The core public API lives in Case; its own bearer checks remain authoritative. */
@Configuration
public class CoreRoutes {

    @Bean
    RouteLocator coreApiRoutes(
            RouteLocatorBuilder builder,
            @Value("${resolveflow.case.base-url:http://127.0.0.1:8083}") String caseBaseUrl) {
        return builder.routes()
                .route("case-core-api", route -> route.path("/api/v1/**").uri(caseBaseUrl))
                .build();
    }
}
