package com.resolveflow.commerce;

import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.test.context.DynamicPropertyRegistry;
import org.springframework.test.context.DynamicPropertySource;
import org.testcontainers.mysql.MySQLContainer;

/**
 * Base for tests that need commerce_db.
 *
 * <p>They run against a real MySQL carrying the real Flyway migrations rather than an in-memory
 * stand-in: the migration and the seed are artifacts under test (docs/engineering.md:68), and an H2
 * "MySQL mode" database would not enforce the CHECK constraints that the amount invariants rely on.
 *
 * <p>The container uses the same image the compose profile pins (mysql:8.4,
 * infra/versions.lock.yaml) and the same schema/account names as
 * infra/mysql/init/01-databases.sql, so a test failure means the real wiring is wrong rather than
 * that the test rig is unusual.
 */
@SpringBootTest
public abstract class CommerceDatabaseTest {

    /**
     * One container for the whole test JVM rather than one per test class.
     *
     * <p>Started explicitly instead of through {@code @Container}: with a {@code static} field JUnit
     * starts and stops the container for every class extending this base, which measured as two full
     * MySQL startups for the two classes here. Ryuk still removes it when the JVM exits.
     */
    static final MySQLContainer MYSQL = new MySQLContainer("mysql:8.4")
            .withDatabaseName("commerce_db")
            .withUsername("commerce")
            .withPassword("commerce");

    static {
        MYSQL.start();
    }

    @DynamicPropertySource
    static void datasourceProperties(DynamicPropertyRegistry registry) {
        // connectionTimeZone=UTC mirrors application.yml: the protocol carries UTC instants
        // (docs/core-contracts.md:17), so the tests would catch a driver that shifted them.
        String url = "jdbc:mysql://" + MYSQL.getHost() + ":" + MYSQL.getMappedPort(MySQLContainer.MYSQL_PORT)
                + "/commerce_db?connectionTimeZone=UTC&preserveInstants=true"
                + "&allowPublicKeyRetrieval=true&useSSL=false";
        registry.add("spring.datasource.url", () -> url);
        registry.add("spring.datasource.username", MYSQL::getUsername);
        registry.add("spring.datasource.password", MYSQL::getPassword);
    }
}
