package com.resolveflow.commerce.refund;

import static org.assertj.core.api.Assertions.assertThat;

import com.resolveflow.commerce.CommerceDatabaseTest;
import com.resolveflow.shared.contract.CanonicalJson;
import java.io.IOException;
import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.nio.file.Files;
import java.nio.file.Path;
import java.time.Duration;
import java.time.Instant;
import java.util.UUID;
import org.junit.jupiter.api.AfterAll;
import org.junit.jupiter.api.BeforeAll;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.test.context.DynamicPropertyRegistry;
import org.springframework.test.context.DynamicPropertySource;
import tools.jackson.databind.ObjectMapper;
import tools.jackson.databind.node.ObjectNode;

/**
 * The refund path against a **real, separate** provider process (C04.3).
 *
 * <p>This is the integration test the plan asks for (tasks/todo.md C04.3 验证: provider协议/重启、成功丢响应集成
 * 测试). The provider is not a mock bolted into this JVM: it is the Python stub from C04.1, started by this
 * test over HTTP and pointed at a throwaway SQLite file. That matters because the interesting failures are
 * cross-boundary ones — a lost response, a 404 from a provider that already took the money, an answer that
 * never arrives at all — and none of them can be produced by a fake that this process controls in memory.
 *
 * <p>The properties under test:
 *
 * <ul>
 *   <li><b>The call is outside the transaction.</b> The operation is IN_PROGRESS and committed before the
 *       provider is asked, so a crash between the two leaves the money reserved and the operation findable.
 *   <li><b>UNKNOWN releases nothing.</b> A timeout, a lost response and a 404 all keep the reservation and
 *       leave the operation reconcilable (docs/domain-model.md:15).
 *   <li><b>A lost response is recovered, not repeated.</b> The provider settled and the caller did not hear;
 *       the retry under the same key returns the original outcome, and the ledger moves exactly once.
 *   <li><b>Reconciliation reads instead of re-requesting.</b> Once the provider knows, {@code reconcile}
 *       applies that outcome.
 * </ul>
 */
class RefundDispatchApiTest extends CommerceDatabaseTest {

    private static final ObjectMapper MAPPER = new ObjectMapper();
    private static final String MERCHANT = "M-1001";
    private static final String LINE_7001 = "7001";

    private static Process providerProcess;

    private static int providerPort;

    private static Path providerDatabase;

    private static final HttpClient HTTP =
            HttpClient.newBuilder().connectTimeout(Duration.ofSeconds(2)).build();

    @BeforeAll
    static void startProvider() throws IOException, InterruptedException {
        Path python = findVenvPython();
        providerDatabase = Files.createTempFile("refund-provider-", ".sqlite3");
        providerPort = freePort();
        ProcessBuilder builder = new ProcessBuilder(
                python.toString(),
                "-m",
                "uvicorn",
                "resolveflow.api.app:app",
                "--host",
                "127.0.0.1",
                "--port",
                String.valueOf(providerPort),
                "--log-level",
                "warning");
        builder.directory(Path.of("").toAbsolutePath().getParent().toFile());
        builder.environment().put("RESOLVEFLOW_PROVIDER_DB", providerDatabase.toString());
        builder.environment().put("RESOLVEFLOW_LAB_ROUTES", "1");
        // Output goes to a file rather than a pipe: a pipe nobody reads can block the child, and this test
        // only needs the server up, not its logs.
        builder.redirectOutput(
                providerDatabase.resolveSibling("provider-stdout.log").toFile());
        builder.redirectError(
                providerDatabase.resolveSibling("provider-stderr.log").toFile());
        providerProcess = builder.start();

        Instant deadline = Instant.now().plusSeconds(30);
        while (Instant.now().isBefore(deadline)) {
            if (health()) {
                return;
            }
            Thread.sleep(200);
        }
        throw new IllegalStateException("the provider stub did not start; see " + providerDatabase.getParent());
    }

    @AfterAll
    static void stopProvider() {
        if (providerProcess != null) {
            providerProcess.destroyForcibly();
            try {
                providerProcess.waitFor();
            } catch (InterruptedException interrupted) {
                Thread.currentThread().interrupt();
            }
        }
        if (providerDatabase != null) {
            try {
                Files.deleteIfExists(providerDatabase);
            } catch (IOException stillHeld) {
                // SQLite on Windows can keep the file mapped for a moment after the process dies. The file
                // lives in the system temp directory, so leaving it is not a leak worth failing a test over.
            }
        }
    }

    @DynamicPropertySource
    static void providerBaseUrl(DynamicPropertyRegistry registry) {
        // Built before the lambda: DynamicPropertySource's supplier may not throw, and the port is known by
        // the time this runs (@BeforeAll starts the provider first).
        String baseUrl = "http://127.0.0.1:" + providerPort;
        registry.add("resolveflow.provider.base-url", () -> baseUrl);
    }

    @Autowired
    RefundAcceptanceService acceptance;

    @Autowired
    RefundDispatchService dispatch;

    @Autowired
    RefundOperationRepository operations;

    @Autowired
    JdbcTemplate jdbc;

    @BeforeEach
    void resetMoneyState() throws IOException, InterruptedException {
        jdbc.execute("DELETE FROM refund_request_inbox");
        jdbc.execute("DELETE FROM refund_operation");
        jdbc.execute("UPDATE line_refund SET state = 'FREE', operation_id = NULL, version = 1");
        jdbc.execute("UPDATE payment_ledger SET refunded_amount = 0, reserved_refund_amount = 0, version = 1");
        clearFaults();
    }

    // ------------------------------------------------------------------ the cases

    @Test
    @DisplayName("a reserved refund is sent to the provider and settles the ledger on success")
    void aSuccessfulRefundSettlesTheLedger() {
        String operationId = operation();
        acceptance.accept("req-1", command(operationId));

        RefundOperationRepository.StoredOperation settled = dispatch.dispatch(operationId);

        assertThat(settled.state()).isEqualTo("SUCCEEDED");
        assertThat(settled.providerRef()).isNotBlank();
        assertThat(settled.settledAt()).isNotNull();
        assertThat(settled.providerKey())
                .as("the key the provider saw is the operation id, so a retry is the same payment")
                .isEqualTo(operationId);
        assertThat(refunded()).isEqualTo(2599);
        assertThat(reserved()).isZero();
        assertThat(slotState()).isEqualTo("CONSUMED");
    }

    @Test
    @DisplayName("a timeout leaves the operation UNKNOWN and keeps the reservation")
    void aTimeoutKeepsTheMoneyReserved() throws IOException, InterruptedException {
        String operationId = operation();
        acceptance.accept("req-1", command(operationId));
        armFault("REQUEST_TIMEOUT", operationId);

        RefundOperationRepository.StoredOperation after = dispatch.dispatch(operationId);

        assertThat(after.state()).isEqualTo(UNKNOWN);
        assertThat(after.retryAt())
                .as("there is a next attempt time to wait for")
                .isNotNull();
        assertThat(reserved())
                .as("no answer is not a failure: the money stays reserved")
                .isEqualTo(2599);
        assertThat(refunded()).isZero();
        assertThat(slotState()).isEqualTo("RESERVED");
    }

    @Test
    @DisplayName("a lost response is recovered by the retry, and the money moves once")
    void aLostResponseIsRecoveredNotRepeated() throws IOException, InterruptedException {
        String operationId = operation();
        acceptance.accept("req-1", command(operationId));
        armFault("LOST_RESPONSE", operationId);

        RefundOperationRepository.StoredOperation lost = dispatch.dispatch(operationId);

        assertThat(lost.state())
                .as("the provider paid, but this call did not hear so: unknown, not failed, and not settled")
                .isEqualTo(UNKNOWN);
        assertThat(lost.reasonCode())
                .as("a lost response is recorded as what it was, so the next reader knows to just ask again")
                .isEqualTo("PROVIDER_RESPONSE_LOST");
        assertThat(reserved()).isEqualTo(2599);
        assertThat(refunded()).isZero();

        // The operation is UNKNOWN, so the next dispatch is allowed to try again — with the same key, which
        // is the only reason the provider can answer with the original outcome instead of paying twice.
        RefundOperationRepository.StoredOperation recovered = dispatch.dispatch(operationId);

        assertThat(recovered.state()).isEqualTo("SUCCEEDED");
        assertThat(recovered.providerRef()).isNotBlank();
        assertThat(refunded())
                .as("exactly one refund, however many attempts it took")
                .isEqualTo(2599);
        assertThat(reserved()).isZero();
        assertThat(slotState()).isEqualTo("CONSUMED");
    }

    @Test
    @DisplayName("a 404 from the provider is unknown, not a failure: the money stays reserved")
    void aNotFoundAnswerKeepsTheMoneyReserved() throws IOException, InterruptedException {
        String operationId = operation();
        acceptance.accept("req-1", command(operationId));
        // A provider that has taken the money but cannot see it yet answers 404 on a query: its window has
        // not elapsed. Releasing here would release money that is already gone (docs/domain-model.md:51).
        armFaultReason("DELAYED_VISIBILITY", operationId, null);
        jdbc.update(
                "UPDATE refund_operation SET state = 'UNKNOWN', retry_at = NULL WHERE operation_id = ?", operationId);

        RefundOperationRepository.StoredOperation reconciled = dispatch.reconcile(operationId);

        assertThat(reconciled.state()).isEqualTo(UNKNOWN);
        assertThat(reserved()).isEqualTo(2599);
        assertThat(slotState()).isEqualTo("RESERVED");
    }

    @Test
    @DisplayName("a determined failure releases the reservation and frees the line")
    void aDeclinedRefundReleasesTheMoney() throws IOException, InterruptedException {
        String operationId = operation();
        acceptance.accept("req-1", command(operationId));
        armFault("DECLINE", operationId, "INSUFFICIENT_FUNDS");

        RefundOperationRepository.StoredOperation failed = dispatch.dispatch(operationId);

        assertThat(failed.state()).isEqualTo("FAILED");
        assertThat(failed.reasonCode()).isEqualTo("INSUFFICIENT_FUNDS");
        assertThat(reserved()).isZero();
        assertThat(refunded()).isZero();
        assertThat(slotState()).isEqualTo("FREE");
    }

    @Test
    @DisplayName("an UNKNOWN operation is reconciled once the provider settles it")
    void anUnknownOperationIsReconciled() throws IOException, InterruptedException {
        String operationId = operation();
        acceptance.accept("req-1", command(operationId));
        armFault("REQUEST_TIMEOUT", operationId);
        assertThat(dispatch.dispatch(operationId).state()).isEqualTo(UNKNOWN);

        settleAtProvider(operationId, "SUCCEEDED");
        RefundOperationRepository.StoredOperation reconciled = dispatch.reconcile(operationId);

        assertThat(reconciled.state()).isEqualTo("SUCCEEDED");
        assertThat(refunded()).isEqualTo(2599);
        assertThat(reserved()).isZero();
        assertThat(slotState()).isEqualTo("CONSUMED");
    }

    @Test
    @DisplayName("reconciliation only picks up operations whose retry time has passed")
    void onlyDueOperationsAreReconciled() throws IOException, InterruptedException {
        String operationId = operation();
        acceptance.accept("req-1", command(operationId));
        armFault("REQUEST_TIMEOUT", operationId);
        dispatch.dispatch(operationId);

        assertThat(dispatch.reconcileDue(10))
                .as("a fresh UNKNOWN has just been written with a backoff, so it is not due yet")
                .isZero();

        settleAtProvider(operationId, "SUCCEEDED");
        jdbc.update("UPDATE refund_operation SET retry_at = ? WHERE operation_id = ?", Instant.now(), operationId);

        assertThat(dispatch.reconcileDue(10)).isEqualTo(1);
        assertThat(operations.find(operationId).state()).isEqualTo("SUCCEEDED");
    }

    @Test
    @DisplayName("dispatching a settled operation again does not ask the provider a second time")
    void aSettledOperationIsNotSentAgain() {
        String operationId = operation();
        acceptance.accept("req-1", command(operationId));
        dispatch.dispatch(operationId);

        RefundOperationRepository.StoredOperation again = dispatch.dispatch(operationId);

        assertThat(again.state()).isEqualTo("SUCCEEDED");
        assertThat(refunded()).isEqualTo(2599);
    }

    // ------------------------------------------------------------------ fixtures

    private static final String UNKNOWN = "UNKNOWN";

    /**
     * An operation id for one test.
     *
     * <p>Shaped like the real thing: the column is {@code CHAR(36)} because a core operation id is the uuid
     * Case pre-allocated, so a test that invented a longer id would be testing a request the protocol cannot
     * produce — and would fail on the column rather than on the property it meant to check.
     */
    private static String operation() {
        return UUID.randomUUID().toString();
    }

    private ObjectNode command(String operationId) {
        ObjectNode node = MAPPER.createObjectNode();
        node.put("operation_id", operationId);
        node.put("case_id", UUID.randomUUID().toString());
        node.put("authorization_id", UUID.randomUUID().toString());
        node.put("input_revision", 2);
        node.put("line_id", LINE_7001);
        node.put("merchant_id", MERCHANT);
        node.put("action", "REFUND");
        node.put("quantity", 2);
        node.put("currency", "CNY");
        node.put("amount_minor", 2599);
        node.put("policy_version", "2026.09");
        node.put("target_service", "commerce-service");
        node.put("payload_hash", CanonicalJson.payloadHash(withoutHash(node)));
        return node;
    }

    private static ObjectNode withoutHash(ObjectNode document) {
        ObjectNode copy = document.deepCopy();
        copy.remove("payload_hash");
        return copy;
    }

    private long refunded() {
        return jdbc.queryForObject(
                "SELECT refunded_amount FROM payment_ledger WHERE order_id = ?", Long.class, orderId());
    }

    private long reserved() {
        return jdbc.queryForObject(
                "SELECT reserved_refund_amount FROM payment_ledger WHERE order_id = ?", Long.class, orderId());
    }

    private String orderId() {
        return jdbc.queryForObject("SELECT order_id FROM order_line WHERE line_id = ?", String.class, LINE_7001);
    }

    private String slotState() {
        return jdbc.queryForObject("SELECT state FROM line_refund WHERE line_id = ?", String.class, LINE_7001);
    }

    private void armFault(String fault, String operationId) throws IOException, InterruptedException {
        armFaultReason(fault, operationId, null);
    }

    private void armFault(String fault, String operationId, String reasonCode)
            throws IOException, InterruptedException {
        armFaultReason(fault, operationId, reasonCode);
    }

    private void armFaultReason(String fault, String operationId, String reasonCode)
            throws IOException, InterruptedException {
        ObjectNode body = MAPPER.createObjectNode();
        body.put("fault", fault);
        body.put("operation_id", operationId);
        if (reasonCode != null) {
            body.put("reason_code", reasonCode);
        }
        assertThat(lab("POST", "/provider/v1/_lab/faults", body.toString()).statusCode())
                .as("the fault was armed; an unarmed fault would make this test prove nothing")
                .isEqualTo(204);
    }

    private void clearFaults() throws IOException, InterruptedException {
        lab("DELETE", "/provider/v1/_lab/faults", null);
    }

    private void settleAtProvider(String operationId, String state) throws IOException, InterruptedException {
        ObjectNode body = MAPPER.createObjectNode();
        body.put("state", state);
        assertThat(lab("POST", "/provider/v1/_lab/operations/" + operationId + "/settle", body.toString())
                        .statusCode())
                .isEqualTo(200);
    }

    private HttpResponse<String> lab(String method, String path, String body) throws IOException, InterruptedException {
        HttpRequest.Builder request = HttpRequest.newBuilder()
                .uri(URI.create("http://127.0.0.1:" + providerPort + path))
                .timeout(Duration.ofSeconds(10));
        if (body == null) {
            request.method(method, HttpRequest.BodyPublishers.noBody());
        } else {
            request.header("Content-Type", "application/json")
                    .method(method, HttpRequest.BodyPublishers.ofString(body));
        }
        return HTTP.send(request.build(), HttpResponse.BodyHandlers.ofString());
    }

    private static boolean health() {
        try {
            HttpResponse<String> response = HTTP.send(
                    HttpRequest.newBuilder()
                            .uri(URI.create("http://127.0.0.1:" + providerPort + "/health"))
                            .timeout(Duration.ofSeconds(2))
                            .GET()
                            .build(),
                    HttpResponse.BodyHandlers.ofString());
            return response.statusCode() == 200 && response.body().contains("\"UP\"");
        } catch (IOException | InterruptedException unavailable) {
            return false;
        }
    }

    /** The agent virtualenv's interpreter, found from the repository rather than from the working directory. */
    private static Path findVenvPython() {
        Path root = Path.of("").toAbsolutePath();
        for (int level = 0; level < 4 && root != null; level++) {
            Path candidate = root.resolve("agent/.venv/Scripts/python.exe");
            if (Files.isExecutable(candidate)) {
                return candidate;
            }
            root = root.getParent();
        }
        throw new IllegalStateException(
                "agent/.venv/Scripts/python.exe not found; the provider stub cannot be started for this test");
    }

    private static int freePort() throws IOException {
        try (java.net.ServerSocket socket = new java.net.ServerSocket(0)) {
            return socket.getLocalPort();
        }
    }
}
