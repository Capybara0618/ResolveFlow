package com.resolveflow.caseservice;

import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;
import org.springframework.scheduling.annotation.EnableScheduling;

/**
 * ResolveFlow case-service. T01 skeleton: starts, exposes health, owns its own database.
 *
 * <p>{@code @EnableScheduling} is here for C05's outbox delivery loop. Nothing else in this service schedules
 * work today, so the annotation is the one place that says "some of this service's work happens on a timer" —
 * a reader looking for what runs without a request starts here.
 */
@SpringBootApplication
@EnableScheduling
public class CaseServiceApplication {

    public static void main(String[] args) {
        SpringApplication.run(CaseServiceApplication.class, args);
    }
}
