package com.resolveflow.caseservice;

import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;
import org.springframework.scheduling.annotation.EnableScheduling;

/**
 * ResolveFlow case-service. T01 skeleton: starts, exposes health, owns its own database.
 *
 * <p>{@code @EnableScheduling} is here for the loops that run without a request: the event outbox delivery
 * loop (C05.1a), the execution dispatch loop that spends an approved authorisation (C05.2a), and the run
 * dispatch loop that hands a case revision to the Agent (C06.3a). Each is a separate bean behind its own
 * property and each is off unless asked for, so the annotation says "some of this service's work happens on a
 * timer" rather than "all of it does" — a reader looking for what runs without a request starts here and
 * then finds out which parts were switched on.
 */
@SpringBootApplication
@EnableScheduling
public class CaseServiceApplication {

    public static void main(String[] args) {
        SpringApplication.run(CaseServiceApplication.class, args);
    }
}
