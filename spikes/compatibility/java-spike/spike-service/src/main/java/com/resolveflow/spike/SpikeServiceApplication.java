package com.resolveflow.spike;

import org.mybatis.spring.annotation.MapperScan;
import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;
import org.springframework.cloud.openfeign.EnableFeignClients;

/**
 * T00 compatibility spike. Exists only to prove the fixed version line
 * (Boot 4.0.x + Cloud 2025.1.x + SCA 2025.1.0.0 + MyBatis + Flyway + MySQL 8.4)
 * actually starts and behaves; production modules are built from T01 onward.
 */
@SpringBootApplication
@EnableFeignClients
@MapperScan("com.resolveflow.spike.entitlement")
public class SpikeServiceApplication {

    public static void main(String[] args) {
        SpringApplication.run(SpikeServiceApplication.class, args);
    }
}