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

    @Autowired
    protected com.resolveflow.caseservice.casefile.CaseCollaborationService collaborations;

    /** Explicit fixture setup: executes the production claim transaction, never an auto-claim on writes. */
    protected void claimTestCase(String caseId) {
        String merchant =
                jdbc.queryForObject("SELECT merchant_id FROM aftersale_case WHERE case_id=?", String.class, caseId);
        String username = jdbc.queryForObject(
                "SELECT username FROM identity_account WHERE merchant_id=? AND role='REVIEWER' AND enabled=TRUE ORDER BY username LIMIT 1",
                String.class,
                merchant);
        claimTestCase(caseId, username);
    }

    protected void claimTestCase(String caseId, String username) {
        var principal = jdbc.queryForObject(
                "SELECT merchant_id,role,identity_version FROM identity_account WHERE username=?",
                (rs, n) -> new com.resolveflow.caseservice.order.RequestPrincipalResolver.Session(
                        new com.resolveflow.shared.security.AuthenticatedPrincipal(
                                username,
                                rs.getString(1),
                                com.resolveflow.shared.security.Role.valueOf(rs.getString(2)),
                                null),
                        rs.getLong(3)),
                username);
        long version = collaborations.read(principal.principal(), caseId).version();
        collaborations.act(
                principal.principal(),
                principal.identityVersion(),
                caseId,
                "\"" + version + "\"",
                new com.resolveflow.caseservice.casefile.CaseCollaborationService.Action("CLAIM", null, "测试夹具显式领取"));
    }

    /** Preserve deliberately stale If-Match assertions; supply only headers absent from the old fixture. */
    protected void addReviewHeaders(org.springframework.http.HttpHeaders headers, String caseId) {
        if (headers.getFirst("If-Match") == null) {
            var versions =
                    jdbc.query("SELECT version FROM aftersale_case WHERE case_id=?", (rs, n) -> rs.getLong(1), caseId);
            headers.set("If-Match", "\"" + (versions.isEmpty() ? 1 : versions.getFirst()) + "\"");
        }
        addCollaborationHeader(headers, caseId);
    }

    protected void addCollaborationHeader(org.springframework.http.HttpHeaders headers, String caseId) {
        var versions =
                jdbc.query("SELECT version FROM case_collaboration WHERE case_id=?", (rs, n) -> rs.getLong(1), caseId);
        headers.set("If-Collaboration-Match", "\"" + (versions.isEmpty() ? 0 : versions.getFirst()) + "\"");
    }

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
        // Every distinct Spring context the suite caches keeps its own Hikari pool, and Spring's default of
        // ten connections per pool outgrew the container's default of 151 once the module reached this many
        // contexts — the run then failed in whichever class started next, with "Too many connections" from
        // Flyway, which reads like a migration problem and is not one. Two connections per context is all a
        // sequential test needs, and the limit belongs to the suite's shape rather than to the class that
        // happened to arrive last.
        registry.add("spring.datasource.hikari.maximum-pool-size", () -> 2);
    }

    /**
     * Empties the case tables for a test that needs a known starting point.
     *
     * <p>The order is the foreign-key order and it lives here rather than in each test: when a child
     * table arrives, exactly one method has to learn about it instead of every cleanup in the suite
     * (case_evidence proved the point — every test that deleted the parent started failing).
     *
     * <p>A verification points at another row of {@code case_evidence} (C03.2c), so the pointers are
     * cleared before the table: the citations are the child side of a foreign key inside one table, and a
     * single {@code DELETE} cannot promise it removes the referenced row after the row that references it.
     */
    protected static void deleteAllCaseData(JdbcTemplate jdbc) {
        jdbc.execute("DELETE FROM case_evidence WHERE reviewed_evidence_id IS NOT NULL");
        for (String table : java.util.List.of(
                // The command table and the outbox are cleaned here because consuming an authorisation writes
                // both (C05.2a), and the command row holds foreign keys into them: a case cannot be deleted
                // while a command still names it.
                // The result inbox points at the case too (C05.2b-3a), so it goes before aftersale_case. A
                // rejected result does not point at a case, but it is cleared with the inbox because the two
                // are one record of what arrived; leaving it behind would let one test's refusal look like the
                // next test's.
                "case_result_inbox",
                "case_result_rejection",
                "case_execution_command",
                "event_outbox",
                "agent_callback",
                // The run binding points at the case (C06.1c), so it goes before aftersale_case. It is
                // listed right after the callback table because the two are one story: a binding is the
                // run a callback will be about.
                "agent_binding",
                "case_authorization",
                "case_proposal",
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

    /** Explicit test-only identities for historical merchant fixtures, never a production JWT bypass. */
    protected void registerTestAccount(String username, String merchant, String role, String customer) {
        jdbc.update(
                "INSERT IGNORE INTO identity_merchant (merchant_id,display_name,enabled) VALUES (?, ?, TRUE)",
                merchant,
                "测试商家 " + merchant);
        jdbc.update("""
                INSERT IGNORE INTO identity_account
                    (username,merchant_id,role,customer_id,display_name,password_hash,enabled,identity_version)
                SELECT ?,?,?,?,? ,password_hash,TRUE,0 FROM identity_account WHERE username='demo-reviewer'
                """, username, merchant, role, customer, username);
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
