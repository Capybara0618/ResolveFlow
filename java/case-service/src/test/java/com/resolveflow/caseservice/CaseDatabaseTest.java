package com.resolveflow.caseservice;

import java.sql.Connection;
import java.sql.SQLException;
import java.time.Duration;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.test.context.DynamicPropertyRegistry;
import org.springframework.test.context.DynamicPropertySource;
import org.testcontainers.mysql.MySQLContainer;

/**
 * A real MySQL for the tests that need one, started once for the whole module.
 *
 * <p>The container uses the same image, schema name and account as compose
 * ({@code infra/compose.yaml}, {@code infra/mysql/init/01-databases.sql}), so a migration that passes
 * here is one that will run there. The container is a singleton rather than a {@code @Container} field:
 * per-class containers started MySQL once per test class and cost most of the suite's runtime.
 *
 * <p>Tests that only need the Spring context (the auth and order tests do) extend this because the
 * application context now genuinely needs case_db: a datasource that cannot connect is a startup
 * failure, not something to paper over in a test.
 */
@SpringBootTest(webEnvironment = SpringBootTest.WebEnvironment.RANDOM_PORT)
public abstract class CaseDatabaseTest {

    static final MySQLContainer MYSQL = new MySQLContainer("mysql:8.4")
            .withDatabaseName("case_db")
            .withUsername("case_svc")
            .withPassword("case_svc");

    static {
        MYSQL.start();
    }

    @DynamicPropertySource
    static void datasourceProperties(DynamicPropertyRegistry registry) {
        registry.add(
                "spring.datasource.url",
                () -> "jdbc:mysql://" + MYSQL.getHost() + ":"
                        + MYSQL.getMappedPort(MySQLContainer.MYSQL_PORT)
                        + "/case_db?connectionTimeZone=UTC&preserveInstants=true&allowPublicKeyRetrieval=true&useSSL=false");
        registry.add("spring.datasource.username", MYSQL::getUsername);
        registry.add("spring.datasource.password", MYSQL::getPassword);
        registry.add("spring.flyway.enabled", () -> true);
        // A slow container start must not read as a migration failure.
        registry.add("spring.flyway.connect-retries", () -> 10);
        registry.add(
                "spring.datasource.hikari.connection-timeout",
                () -> Duration.ofSeconds(30).toMillis());
    }

    protected static Connection connectToCaseDb() throws SQLException {
        return java.sql.DriverManager.getConnection(
                "jdbc:mysql://" + MYSQL.getHost() + ":" + MYSQL.getMappedPort(MySQLContainer.MYSQL_PORT)
                        + "/case_db?allowPublicKeyRetrieval=true&useSSL=false",
                MYSQL.getUsername(),
                MYSQL.getPassword());
    }
}
