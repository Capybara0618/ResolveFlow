package com.resolveflow.gateway;

import static org.assertj.core.api.Assertions.assertThat;

import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.boot.webtestclient.autoconfigure.AutoConfigureWebTestClient;
import org.springframework.test.web.reactive.server.WebTestClient;

/**
 * T01 acceptance: the gateway starts and its health state is readable over the
 * reactive stack. WebTestClient is the reactive-side client; RestTestClient is the
 * servlet-side one, so the two stacks use different test starters in Boot 4.
 */
@SpringBootTest(webEnvironment = SpringBootTest.WebEnvironment.RANDOM_PORT)
@AutoConfigureWebTestClient
class GatewayApplicationTest {

    @Autowired
    WebTestClient webTestClient;

    @Test
    @DisplayName("The application context starts")
    void contextLoads() {
        // Fails if any auto-configuration is unsatisfied on this version line.
    }

    @Test
    @DisplayName("Health endpoint reports UP")
    void healthEndpointReportsUp() {
        webTestClient
                .get()
                .uri("/actuator/health")
                .exchange()
                .expectStatus()
                .isOk()
                .expectBody(String.class)
                .value(body -> assertThat(body).contains("\"status\":\"UP\""));
    }
}
