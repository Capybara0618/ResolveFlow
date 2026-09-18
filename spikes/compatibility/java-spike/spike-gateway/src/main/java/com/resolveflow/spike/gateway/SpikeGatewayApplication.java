package com.resolveflow.spike.gateway;

import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;

/**
 * T00 gateway spike: proves the Cloud 2025.1 gateway starter routes to a Nacos-discovered
 * service by logical name. Note the artifact rename — spring-cloud-starter-gateway does
 * not exist at 5.x.
 */
@SpringBootApplication
public class SpikeGatewayApplication {

    public static void main(String[] args) {
        SpringApplication.run(SpikeGatewayApplication.class, args);
    }
}