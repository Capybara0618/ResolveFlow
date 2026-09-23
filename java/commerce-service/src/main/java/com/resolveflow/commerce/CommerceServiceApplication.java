package com.resolveflow.commerce;

import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;
import org.springframework.scheduling.annotation.EnableScheduling;

/**
 * ResolveFlow commerce-service. T01 skeleton: starts, exposes health, owns its own database.
 *
 * <p><b>{@code @EnableScheduling} was missing here, and this service had three loops because of it.</b> C05.2b
 * wrote {@code ResultOutboxDeliveryLoop} and C05.2c wrote {@code RefundDispatchLoop} and
 * {@code RefundReconcileLoop}, each as a {@code @Scheduled} shell around an act that is tested by calling the
 * act itself — which is the project's convention and is exactly why nothing caught this: without the
 * annotation Spring registers the beans and never schedules them, so a real deployment reserved the money,
 * wrote the operation and stopped. The whole-chain e2e (C05.2c-3) is what found it, by running the real
 * services in separate processes for the first time: the operation sat in {@code RECEIVED} for ninety seconds
 * with every switch turned on, and the only reason it had ever looked fine is that every test called the loop's
 * method directly.
 *
 * <p>It is here for the same reason as in case-service: the loops are off by default, so enabling scheduling
 * costs nothing until a switch asks for work, and a switch that asks for work must actually get it.
 */
@SpringBootApplication
@EnableScheduling
public class CommerceServiceApplication {

    public static void main(String[] args) {
        SpringApplication.run(CommerceServiceApplication.class, args);
    }
}
