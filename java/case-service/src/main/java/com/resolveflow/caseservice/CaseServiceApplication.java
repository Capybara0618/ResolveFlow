package com.resolveflow.caseservice;

import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;

/**
 * ResolveFlow case-service. T01 skeleton: starts, exposes health, owns its own database.
 */
@SpringBootApplication
public class CaseServiceApplication {

    public static void main(String[] args) {
        SpringApplication.run(CaseServiceApplication.class, args);
    }
}
