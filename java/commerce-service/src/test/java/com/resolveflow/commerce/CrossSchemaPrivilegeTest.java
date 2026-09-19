package com.resolveflow.commerce;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

import java.nio.file.Files;
import java.nio.file.Path;
import java.sql.Connection;
import java.sql.DriverManager;
import java.sql.ResultSet;
import java.sql.SQLException;
import java.sql.Statement;
import org.junit.jupiter.api.BeforeAll;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.testcontainers.containers.Container;
import org.testcontainers.utility.MountableFile;

/**
 * "独立数据库账户不跨库读取" (docs/engineering.md:60, infra/mysql/init/01-databases.sql).
 *
 * <p>The claim is that one MySQL container hosting three schemas does not mean one service can read
 * another's tables. That is a property of the grants, not of the code, so it is proved by connecting
 * as the real accounts against the real init script — the same file compose mounts — rather than by
 * asserting on a configuration file.
 *
 * <p>The script is applied to the test container as-is: if someone widens a grant there, this test
 * fails, which is the only reason a grant file is worth having.
 */
class CrossSchemaPrivilegeTest extends CommerceDatabaseTest {

    private static final String INIT_SCRIPT = "../../infra/mysql/init/01-databases.sql";

    private static final String CASE_TABLE = "case_db.privilege_probe";

    @BeforeAll
    static void applyTheRealInitScript() throws Exception {
        Path script = Path.of(INIT_SCRIPT).toAbsolutePath().normalize();
        assertThat(Files.exists(script))
                .as("the compose init script must exist at %s so this test proves the real grants", script)
                .isTrue();
        MYSQL.copyFileToContainer(MountableFile.forHostPath(script), "/tmp/01-databases.sql");
        // The container's root credentials come from Testcontainers; the script then creates the
        // per-service accounts exactly as a fresh compose volume would.
        Container.ExecResult result =
                MYSQL.execInContainer("sh", "-c", "mysql -uroot -p" + MYSQL.getPassword() + " < /tmp/01-databases.sql");
        assertThat(result.getExitCode())
                .as("applying infra/mysql/init/01-databases.sql: %s", result.getStderr())
                .isZero();
    }

    private static Connection connect(String user, String password, String database) throws SQLException {
        String url = "jdbc:mysql://" + MYSQL.getHost() + ":"
                + MYSQL.getMappedPort(org.testcontainers.mysql.MySQLContainer.MYSQL_PORT) + "/" + database
                + "?allowPublicKeyRetrieval=true&useSSL=false";
        return DriverManager.getConnection(url, user, password);
    }

    @Test
    @DisplayName("the commerce account reads commerce_db and is refused case_db")
    void commerceCannotReadCaseDb() throws Exception {
        try (Connection commerce = connect("commerce", "commerce", "commerce_db");
                Statement statement = commerce.createStatement()) {
            try (ResultSet rows = statement.executeQuery("SELECT COUNT(*) FROM order_line")) {
                assertThat(rows.next()).isTrue();
                assertThat(rows.getInt(1)).isPositive();
            }

            // A table that definitely exists in case_db, created as root, so the failure below can
            // only be a privilege failure rather than "no such table".
            assertThatThrownBy(() -> statement.executeQuery("SELECT COUNT(*) FROM " + CASE_TABLE))
                    .isInstanceOf(SQLException.class)
                    .hasMessageContaining("denied");
        }
    }

    @Test
    @DisplayName("the case account reads case_db and is refused commerce_db")
    void caseCannotReadCommerceDb() throws Exception {
        createKeywordProbe();

        try (Connection caseService = connect("case_svc", "case_svc", "case_db");
                Statement statement = caseService.createStatement()) {
            try (ResultSet rows = statement.executeQuery("SELECT COUNT(*) FROM privilege_probe")) {
                assertThat(rows.next()).isTrue();
            }

            assertThatThrownBy(() -> statement.executeQuery("SELECT COUNT(*) FROM commerce_db.order_line"))
                    .isInstanceOf(SQLException.class)
                    .hasMessageContaining("denied");
        }
    }

    @Test
    @DisplayName("neither account holds privileges outside its own schema")
    void grantsStayInsideTheOwnSchema() throws Exception {
        createKeywordProbe();

        try (Connection commerce = connect("commerce", "commerce", "commerce_db");
                Statement statement = commerce.createStatement();
                ResultSet grants = statement.executeQuery("SHOW GRANTS FOR CURRENT_USER()")) {
            StringBuilder all = new StringBuilder();
            while (grants.next()) {
                all.append(grants.getString(1)).append('\n');
            }
            assertThat(all.toString())
                    .contains("commerce_db")
                    .doesNotContain("case_db")
                    .doesNotContain("fulfillment_db");
        }
    }

    /** Create the probe table in case_db once, as root, so both directions have something to read. */
    private static void createKeywordProbe() throws Exception {
        Container.ExecResult result = MYSQL.execInContainer(
                "sh",
                "-c",
                "mysql -uroot -p" + MYSQL.getPassword()
                        + " -e \"CREATE TABLE IF NOT EXISTS case_db.privilege_probe (id INT PRIMARY KEY)\"");
        assertThat(result.getExitCode())
                .as("creating the probe table: %s", result.getStderr())
                .isZero();
    }
}
