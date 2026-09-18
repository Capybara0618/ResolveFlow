package com.resolveflow.commerce;

import static org.assertj.core.api.Assertions.assertThat;

import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.resttestclient.autoconfigure.AutoConfigureRestTestClient;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.test.web.servlet.client.RestTestClient;

/**
 * T01 acceptance: the service starts and its health state is readable.
 * A service that boots but cannot report health is not deployable.
 *
 * <p>Uses RestTestClient — Boot 4 removed TestRestTemplate; the Spring Framework 7
 * replacement lives in the webmvc test starter (see docs/compatibility-report.md).
 */
@SpringBootTest(webEnvironment = SpringBootTest.WebEnvironment.RANDOM_PORT)
@AutoConfigureRestTestClient
class CommerceServiceApplicationTest {

    @Autowired
    RestTestClient rest;

    @Test
    @DisplayName("The application context starts")
    void contextLoads() {
        // Fails if any auto-configuration is unsatisfied on this version line.
    }

    @Test
    @DisplayName("Health endpoint reports UP")
    void healthEndpointReportsUp() {
        rest.get()
                .uri("/actuator/health")
                .exchange()
                .expectStatus()
                .isOk()
                .expectBody(String.class)
                .value(body -> assertThat(body).contains("\"status\":\"UP\""));
    }
}
