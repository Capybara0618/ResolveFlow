package com.resolveflow.caseservice.order;

import org.springframework.boot.autoconfigure.condition.ConditionalOnMissingBean;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.web.client.RestClient;

/**
 * The outbound HTTP client Case uses to reach Commerce.
 *
 * <p>The builder is a bean so a test can bind a mock server to it and observe what Case actually
 * sends — the scope it derived and the service token it presented — rather than assert on a client
 * that was constructed inside the class under test.
 */
@Configuration
public class OrderReadConfiguration {

    @Bean
    @ConditionalOnMissingBean(RestClient.Builder.class)
    RestClient.Builder resolveflowRestClientBuilder() {
        return RestClient.builder();
    }
}
