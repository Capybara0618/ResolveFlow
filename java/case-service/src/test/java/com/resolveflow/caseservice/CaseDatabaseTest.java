package com.resolveflow.caseservice;

import java.nio.file.Files;
import java.nio.file.Path;
import java.sql.Connection;
import java.sql.SQLException;
import java.time.Duration;
import org.junit.jupiter.api.BeforeEach;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.jdbc.core.JdbcTemplate;
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

    @Autowired
    protected JdbcTemplate jdbc;

    @Autowired
    protected com.resolveflow.caseservice.policy.PolicyImportService policies;

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

    /**
     * Empties the case tables for a test that needs a known starting point.
     *
     * <p>The order is the foreign-key order and it lives here rather than in each test: when a child
     * table arrives, exactly one method has to learn about it instead of every cleanup in the suite
     * (case_evidence proved the point — every test that deleted the parent started failing).
     */
    protected static void deleteAllCaseData(JdbcTemplate jdbc) {
        for (String table : java.util.List.of(
                "case_evidence",
                "case_policy_bundle",
                "case_policy_manifest",
                "request_idempotency",
                "case_timeline",
                "active_case_slot",
                "case_requested_action",
                "aftersale_case")) {
            jdbc.execute("DELETE FROM " + table);
        }
    }

    /**
     * Makes sure a policy version is installed, because a case cannot be opened without one.
     *
     * <p>Every case-opening test needs this, and every one of them needs the version whose window covers
     * the payment time the Commerce stub reports. The bundles are the repository's own fixtures rather than
     * test copies: importing them here is also the cheapest proof that the shipped policy files are
     * importable, and it keeps one definition of what the demo policy says.
     */
    @BeforeEach
    void ensurePolicyBundlesAreInstalled() {
        if (jdbc.queryForObject("SELECT COUNT(*) FROM policy_bundle", Integer.class) > 0) {
            return;
        }
        policies.importDirectory(policyFixtures());
    }

    /**
     * The repository's {@code fixtures/policies/bundles}, found from wherever the test JVM started.
     *
     * <p>Surefire's working directory is the module, and a run driven from the repository root is the other
     * thing people do. Rather than pick one and be wrong half the time, this walks up until it finds the
     * directory and fails with the place it started from.
     */
    private static Path policyFixtures() {
        Path candidate = Path.of("").toAbsolutePath();
        for (int level = 0; level < 5 && candidate != null; level++) {
            Path bundles = candidate.resolve("fixtures").resolve("policies").resolve("bundles");
            if (Files.isDirectory(bundles)) {
                return bundles;
            }
            candidate = candidate.getParent();
        }
        throw new IllegalStateException(
                "fixtures/policies/bundles not found above " + Path.of("").toAbsolutePath());
    }

    protected static Connection connectToCaseDb() throws SQLException {
        return java.sql.DriverManager.getConnection(
                "jdbc:mysql://" + MYSQL.getHost() + ":" + MYSQL.getMappedPort(MySQLContainer.MYSQL_PORT)
                        + "/case_db?allowPublicKeyRetrieval=true&useSSL=false",
                MYSQL.getUsername(),
                MYSQL.getPassword());
    }
}
