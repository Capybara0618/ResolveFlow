package com.resolveflow.fulfillment;

import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;

/**
 * ResolveFlow fulfillment-service. T01 skeleton: starts, exposes health, owns its own database.
 */
@SpringBootApplication
public class FulfillmentServiceApplication {

    public static void main(String[] args) {
        SpringApplication.run(FulfillmentServiceApplication.class, args);
    }
}
