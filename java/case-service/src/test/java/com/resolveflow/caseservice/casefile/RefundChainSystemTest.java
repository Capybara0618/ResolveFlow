package com.resolveflow.caseservice.casefile;

import static org.assertj.core.api.Assertions.assertThat;

import com.resolveflow.caseservice.policy.PolicyRule;
import com.resolveflow.shared.security.AuthenticatedPrincipal;
import com.resolveflow.shared.security.JwtCodec;
import com.resolveflow.shared.security.Role;
import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.sql.Connection;
import java.sql.DriverManager;
import java.sql.ResultSet;
import java.sql.SQLException;
import java.sql.Statement;
import java.time.Duration;
import java.time.Instant;
import java.util.ArrayList;
import java.util.List;
import java.util.UUID;
import org.junit.jupiter.api.Assumptions;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.condition.EnabledIfEnvironmentVariable;
import tools.jackson.databind.JsonNode;
import tools.jackson.databind.ObjectMapper;
import tools.jackson.databind.node.ObjectNode;

/**
 * C05.2c: the whole refund chain, over the real broker and the real databases.
 *
 * <p>Every other test in this module stops one step short of this one. {@code CaseResultConsumerApiTest}
 * proves the projection by calling {@code consume} itself; {@code CoreEventTransportSystemTest} proves the
 * command reaches Commerce over a real topic; the commerce module's tests stop at a reserved or settled
 * operation. None of them answers the question this project actually makes a claim about: <em>does a refund
 * that a reviewer approved come back and close the case, with no hand-offs</em>? This test does nothing by
 * hand: it opens a case through the public API, delivers a proposal the way the Agent would, approves it as a
 * reviewer, and then waits for three separate processes and two RocketMQ topics to finish the job.
 *
 * <p><b>What it deliberately does not do.</b> It does not start anything (the driver does), it does not write
 * an outbox row directly (that is C05.1c's job, and doing it here would hide the writer that C05.2a built),
 * and it does not call {@code dispatch} or {@code consume} at all. It talks HTTP to the running case-service,
 * reads the two real schemas over JDBC, and asserts what the chain did.
 *
 * <p>Its opt-in switch is an environment variable rather than a system property, for the reason C05.1c
 * recorded: the default suite must stay runnable with no broker, and Maven does not promise to forward
 * {@code -D} to the forked test JVM the way it forwards the environment.
 *
 * <p><b>The duplicate at the end is the point of the second half.</b> After the case is closed, the result row
 * is put back to {@code PENDING} with its bytes untouched, so the real delivery loop republishes exactly the
 * document that was signed. A second delivery of the same outcome must change nothing: that is at-least-once,
 * said in the only place where it can be said convincingly.
 */
@EnabledIfEnvironmentVariable(named = "RESOLVEFLOW_E2E_CHAIN", matches = "true")
class RefundChainSystemTest {

    private static final ObjectMapper MAPPER = new ObjectMapper();
    private static final HttpClient HTTP =
            HttpClient.newBuilder().connectTimeout(Duration.ofSeconds(5)).build();
    private static final String TRACEPARENT = "00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01";
    private static final Duration CHAIN_TIMEOUT = Duration.ofSeconds(90);

    /** Where the running case-service is. A driver starts it; nothing here starts a server. */
    private static final String CASE_BASE = env("RESOLVEFLOW_E2E_CASE_BASE", "http://127.0.0.1:8083");

    private static final String MYSQL_HOST = env("RESOLVEFLOW_E2E_MYSQL_HOST", "127.0.0.1");
    private static final String MYSQL_ROOT_PASSWORD = env("RESOLVEFLOW_E2E_MYSQL_ROOT_PASSWORD", "root");

    /** The demo line this run refunds. Read from the database rather than assumed, like every other fact here. */
    private static final String LINE_ID = env("RESOLVEFLOW_E2E_LINE", "7101");

    /**
     * The second line, which the CF3 run refunds. Blank when nobody started a provider for this test to arm a
     * fault in, in which case that test skips rather than fails: the happy path above needs no provider of its
     * own, and a test that quietly drove somebody else's provider would be worse than one that says it skipped.
     */
    private static final String LINE_UNKNOWN = env("RESOLVEFLOW_E2E_LINE_UNKNOWN", "");

    /**
     * A third line, which commerce will refuse to refund: it exists in {@code order_line} and has no
     * {@code line_refund} row, so the acceptance path answers {@code LINE_NOT_FOUND}. The driver mints it with
     * {@code slot=False}, which is the state its own mint produced by accident in C05.2c-3 — the run that first
     * showed a case sitting in EXECUTING with nobody ever telling it why. Blank when no such line was minted, in
     * which case the refusal test skips rather than fails.
     */
    private static final String LINE_REFUSED = env("RESOLVEFLOW_E2E_LINE_REFUSED", "");

    /**
     * Where the provider stub is. The driver starts one per run on a free port with its lab surface on, and
     * passes it down; the default is the port the module tests and the README use.
     */
    private static final String PROVIDER_BASE = env("RESOLVEFLOW_E2E_PROVIDER_BASE", "http://127.0.0.1:8090");

    /**
     * The demonstration identity secret, and the reason it is a default rather than a required environment
     * value: {@code case-service}'s own {@code application.yml} ships this exact local secret and says it is a
     * local default rather than a deployment key. Overridable so the test is not pinned to it.
     */
    private static final String JWT_SECRET = env("RESOLVEFLOW_E2E_JWT_SECRET", "resolveflow-core-demo-identity-secret");

    @Test
    @DisplayName("an approved refund travels the whole chain and closes the case — then a duplicate changes nothing")
    void theApprovedRefundClosesTheCaseOverTheRealBroker() throws Exception {
        ApprovedCase run = driveToApproval(LINE_ID);
        String caseId = run.caseId();
        String orderId = run.line().orderId();
        long amount = run.line().amount();

        // ---------------------------------------------------------------- the chain, with nobody's help
        // Waiting on the slot's state='RESERVED' would race the very thing being waited for: the reservation is
        // durable, but the slot only *rests* in RESERVED for one poll interval before the dispatch loop sends it
        // on. This test lost that race for its first ninety seconds (C05.2c-3) — a probe for a transient state
        // asserts the shape of the timing rather than the fact. What is durable is the operation row: the
        // reservation and that insert are one transaction, so the row's existence *is* the reservation.
        String operationId = await(
                "Commerce accepts the command and writes the operation it owes",
                () -> scalar(
                        "commerce_db",
                        "SELECT operation_id FROM refund_operation WHERE line_id = '" + LINE_ID
                                + "' ORDER BY reserved_at DESC LIMIT 1"),
                CHAIN_TIMEOUT);
        assertThat(scalar("case_db", "SELECT status FROM aftersale_case WHERE case_id = '" + caseId + "'"))
                .as("approving and dispatching are Case's own steps and must have happened before the money")
                .isIn("EXECUTING", "CLOSED_SUCCESS");

        await(
                "Commerce sends the reservation to the provider and the provider settles it",
                () -> "SUCCEEDED".equals(operationState(operationId)) ? "settled" : null,
                CHAIN_TIMEOUT);
        await(
                "the case hears the outcome and closes itself",
                () -> "CLOSED_SUCCESS".equals(caseStatus(caseId)) ? "closed" : null,
                CHAIN_TIMEOUT);

        // ---------------------------------------------------------------- the invariants
        assertThat(scalar("commerce_db", "SELECT COUNT(*) FROM refund_operation WHERE case_id = '" + caseId + "'"))
                .as("one approved authorisation is one refund: a second operation for the same case would mean"
                        + " the command writer or the sweeper dispatched it twice")
                .isEqualTo("1");
        assertThat(scalar(
                        "commerce_db",
                        "SELECT COUNT(*) FROM refund_operation WHERE line_id = '" + LINE_ID + "'"
                                + " AND state = 'SUCCEEDED'"))
                .as("at most one successful refund per line (docs/domain-model.md)")
                .isEqualTo("1");
        assertThat(scalar(
                        "commerce_db", "SELECT refunded_amount FROM payment_ledger WHERE order_id = '" + orderId + "'"))
                .as("exactly the line's amount was refunded")
                .isEqualTo(String.valueOf(amount));
        assertThat(scalar(
                        "commerce_db",
                        "SELECT reserved_refund_amount FROM payment_ledger WHERE order_id = '" + orderId + "'"))
                .as("a settled refund leaves nothing reserved behind it")
                .isEqualTo("0");
        assertThat(scalar("commerce_db", "SELECT state FROM line_refund WHERE line_id = '" + LINE_ID + "'"))
                .as("the line can never be refunded again")
                .isEqualTo("CONSUMED");
        assertThat(scalar("commerce_db", "SELECT operation_id FROM line_refund WHERE line_id = '" + LINE_ID + "'"))
                .as("the slot names this very operation, which is the durable record that it was reserved for it:"
                        + " the holder is written in the same transaction as the reservation, and the slot is what"
                        + " stops a second refund of the line")
                .isEqualTo(operationId);

        // The case's own record of what it was told.
        List<String> inbox = row(
                "case_db",
                "SELECT disposition, IFNULL(detail, '-'), deliveries, IFNULL(projected_at, 'NULL'), state,"
                        + " amount_minor, aggregate_version, signing_key_id"
                        + " FROM case_result_inbox WHERE operation_id = '" + operationId + "'");
        assertThat(inbox).as("exactly one result inbox row for this operation").hasSize(8);
        assertThat(inbox.get(0)).as("disposition").isEqualTo("ACCEPTED");
        assertThat(inbox.get(2)).as("deliveries").isEqualTo("1");
        assertThat(inbox.get(3))
                .as("projected_at is set: the row was consumed by the projection")
                .isNotEqualTo("NULL");
        assertThat(inbox.get(4)).as("state stored from the signed payload").isEqualTo("SUCCEEDED");
        assertThat(inbox.get(5)).as("amount").isEqualTo(String.valueOf(amount));
        assertThat(inbox.get(6)).as("aggregate_version").isNotEqualTo("0");
        assertThat(inbox.get(7)).as("signing_key_id").isEqualTo("commerce-service-demo-key");

        assertThat(scalar(
                        "case_db",
                        "SELECT COUNT(*) FROM case_timeline WHERE case_id = '" + caseId + "' AND kind = 'CASE_CLOSED'"))
                .as("the projection records the closing exactly once")
                .isEqualTo("1");

        // ---------------------------------------------------------------- a second delivery of the same outcome
        String resultEventId = scalar(
                "commerce_db",
                "SELECT event_id FROM event_outbox WHERE event_type = 'RefundSucceeded' AND envelope LIKE '%"
                        + operationId + "%' ORDER BY created_at DESC LIMIT 1");
        assertThat(resultEventId)
                .as("the success must have been written to commerce's outbox — that row is the event under test")
                .isNotNull();
        String envelopeBefore =
                scalar("commerce_db", "SELECT envelope FROM event_outbox WHERE event_id = '" + resultEventId + "'");

        // Put the row back to the state the delivery loop picks up, leaving the signed bytes untouched: this is
        // the same document, delivered twice, which is what at-least-once means.
        update(
                "commerce_db",
                "UPDATE event_outbox SET status = 'PENDING', published_at = NULL, next_attempt_at = NULL"
                        + " WHERE event_id = '" + resultEventId + "'");

        await(
                "the delivery loop republishes the identical bytes",
                () -> "2"
                                .equals(scalar(
                                        "commerce_db",
                                        "SELECT attempts FROM event_outbox WHERE event_id = '" + resultEventId
                                                + "' AND status = 'PUBLISHED'"))
                        ? "republished"
                        : null,
                CHAIN_TIMEOUT);
        assertThat(scalar("commerce_db", "SELECT envelope FROM event_outbox WHERE event_id = '" + resultEventId + "'"))
                .as("the republished row is byte-identical: nothing rewrote a signed document")
                .isEqualTo(envelopeBefore);

        await(
                "the case records the second delivery of the same event",
                () -> "2"
                                .equals(scalar(
                                        "case_db",
                                        "SELECT deliveries FROM case_result_inbox WHERE operation_id = '" + operationId
                                                + "'"))
                        ? "redelivered"
                        : null,
                CHAIN_TIMEOUT);

        List<String> after = row(
                "case_db",
                "SELECT disposition, IFNULL(detail, '-'), deliveries, IFNULL(projected_at, 'NULL')"
                        + " FROM case_result_inbox WHERE operation_id = '" + operationId + "'");
        assertThat(after.get(0))
                .as("a duplicate is still an accepted fact, not a refusal")
                .isEqualTo("ACCEPTED");
        assertThat(after.get(1)).as("the duplicate is recorded as what it was").isEqualTo("duplicate delivery ignored");
        assertThat(after.get(3))
                .as("the projection is not re-run for a duplicate")
                .isNotEqualTo("NULL");
        assertThat(scalar(
                        "case_db", "SELECT COUNT(*) FROM case_result_inbox WHERE operation_id = '" + operationId + "'"))
                .as("a redelivery does not store a second fact")
                .isEqualTo("1");
        assertThat(scalar(
                        "case_db",
                        "SELECT COUNT(*) FROM case_timeline WHERE case_id = '" + caseId + "' AND kind = 'CASE_CLOSED'"))
                .as("and it does not close the case a second time")
                .isEqualTo("1");
        assertThat(caseStatus(caseId)).as("the case stays closed").isEqualTo("CLOSED_SUCCESS");
        assertThat(scalar(
                        "commerce_db", "SELECT refunded_amount FROM payment_ledger WHERE order_id = '" + orderId + "'"))
                .as("the duplicate moved no money")
                .isEqualTo(String.valueOf(amount));
    }

    /**
     * CF3: the provider settles the refund and the answer never arrives.
     *
     * <p>This is the case the whole reservation design exists for, and it is the only one where the two sides of
     * the system genuinely disagree: Commerce knows nothing, the provider has already moved the money. Every
     * cheap answer is wrong here — releasing the reservation loses a refund that happened, failing the operation
     * does the same, and sending a new request under a new id pays twice. So the operation becomes
     * {@code UNKNOWN}, the money stays reserved, and the only way out is to ask the provider what happened.
     *
     * <p>The fault is armed for <em>this operation id</em> after the reservation exists, never for "every
     * operation": a fault armed globally would leak into the happy-path test in the same JVM, and the order two
     * JUnit methods run in is not something to build a test on. Arming it late is only possible because the
     * driver runs the dispatch loop on a long poll interval, which is what makes this deterministic instead of a
     * race — the window is seconds wide, not milliseconds.
     */
    @Test
    @DisplayName("a lost answer leaves UNKNOWN with the money reserved, and one reconciliation settles it — once")
    void theUnknownFromALostResponseIsReconciledWithoutPayingTwice() throws Exception {
        Assumptions.assumeTrue(
                !LINE_UNKNOWN.isBlank(),
                "the CF3 run needs its own line and a provider with its lab surface on (RESOLVEFLOW_E2E_LINE_UNKNOWN)");

        ApprovedCase run = driveToApproval(LINE_UNKNOWN);
        String caseId = run.caseId();
        LineFacts line = run.line();

        String operationId = await(
                "Commerce accepts the command and writes the operation it owes",
                () -> scalar(
                        "commerce_db",
                        "SELECT operation_id FROM refund_operation WHERE line_id = '" + line.lineId()
                                + "' ORDER BY reserved_at DESC LIMIT 1"),
                CHAIN_TIMEOUT);
        assertThat(armFault("LOST_RESPONSE", operationId))
                .as("the provider's lab surface took the fault. A lab tool that silently did nothing would let"
                        + " this test pass without any fault armed at all")
                .isTrue();

        await(
                "Commerce records the missing answer as UNKNOWN, releasing nothing",
                () -> "UNKNOWN".equals(operationState(operationId)) ? "unknown" : null,
                CHAIN_TIMEOUT);

        // CF3 stated in the databases, which is the only place it counts.
        assertThat(scalar(
                        "commerce_db",
                        "SELECT refunded_amount FROM payment_ledger WHERE order_id = '" + line.orderId() + "'"))
                .as("UNKNOWN is not a refund: nothing is settled")
                .isEqualTo("0");
        assertThat(scalar(
                        "commerce_db",
                        "SELECT reserved_refund_amount FROM payment_ledger WHERE order_id = '" + line.orderId() + "'"))
                .as("and it is not a release either — the reservation is what the retry will spend")
                .isEqualTo(String.valueOf(line.amount()));
        assertThat(scalar("commerce_db", "SELECT state FROM line_refund WHERE line_id = '" + line.lineId() + "'"))
                .as("the line stays held by the operation nobody has an answer for")
                .isEqualTo("RESERVED");
        // The case's own reaction is a further two hops away (commerce outbox → broker → case listener → projection),
        // so it is awaited rather than asserted. Asserting it right after Commerce goes UNKNOWN is the same
        // mistake as probing the reserved slot, one level down — and it failed the same way (C05.2c-4).
        await(
                "the case is told the outcome is not final",
                () -> "RECONCILING".equals(caseStatus(caseId)) ? "reconciling" : null,
                CHAIN_TIMEOUT);
        assertThat(scalar(
                        "case_db",
                        "SELECT event_type FROM case_result_inbox WHERE operation_id = '" + operationId + "'"))
                .as("the case IS told about the unknown — leaving it in the dark would leave an operator with no"
                        + " trace of a refund that is neither done nor not done")
                .isEqualTo("RefundUnknown");
        assertThat(scalar("case_db", "SELECT state FROM case_result_inbox WHERE operation_id = '" + operationId + "'"))
                .isEqualTo("UNKNOWN");
        assertThat(scalar(
                        "case_db",
                        "SELECT projected_at IS NOT NULL FROM case_result_inbox WHERE operation_id = '" + operationId
                                + "'"))
                .as("and it was consumed by the projection rather than parked")
                .isEqualTo("1");
        assertThat(caseStatus(caseId))
                .as("the case now waits: RECONCILING is the state that says an outcome exists and is not final")
                .isEqualTo("RECONCILING");
        assertThat(scalar(
                        "case_db",
                        "SELECT COUNT(*) FROM case_timeline WHERE case_id = '" + caseId + "' AND kind = 'CASE_CLOSED'"))
                .as("and it is certainly not closed on an unknown")
                .isEqualTo("0");

        // The divergence itself: Commerce does not know, and the provider has already settled. That gap is the
        // lost response, and it is why "just ask again" is the only correct move. (`responded` is deliberately
        // not asserted here: the query is answered *now*, so the provider reports responded=true — only the
        // reply that was lost was unanswered, and that reply is gone.)
        JsonNode providerView = providerRefund(operationId);
        assertThat(providerView.get("state").stringValue())
                .as("the provider settled this refund and recorded it; only the answer went missing")
                .isEqualTo("SUCCEEDED");
        String providerRef = providerView.get("provider_ref").stringValue();

        assertThat(clearFaults())
                .as("the fault is cleared so the retry gets a real answer")
                .isTrue();

        // Nobody calls reconcile(id) here: the loop waits out the domain's own backoff, asks the provider what
        // happened, and settles on the answer it gets.
        await(
                "the reconciliation resolves the unknown without a second request",
                () -> "SUCCEEDED".equals(operationState(operationId)) ? "settled" : null,
                CHAIN_TIMEOUT);
        await(
                "the case hears the recovered outcome and closes itself",
                () -> "CLOSED_SUCCESS".equals(caseStatus(caseId)) ? "closed" : null,
                CHAIN_TIMEOUT);

        assertThat(scalar(
                        "commerce_db",
                        "SELECT provider_ref FROM refund_operation WHERE operation_id = '" + operationId + "'"))
                .as("the operation adopted the provider's own reference: the retry asked about the same refund"
                        + " rather than buying a second one")
                .isEqualTo(providerRef);
        assertThat(scalar(
                        "commerce_db", "SELECT COUNT(*) FROM refund_operation WHERE line_id = '" + line.lineId() + "'"))
                .as("one reservation, one operation: UNKNOWN never means a new id and a new payment")
                .isEqualTo("1");
        assertThat(scalar(
                        "commerce_db",
                        "SELECT refunded_amount FROM payment_ledger WHERE order_id = '" + line.orderId() + "'"))
                .isEqualTo(String.valueOf(line.amount()));
        assertThat(scalar(
                        "commerce_db",
                        "SELECT reserved_refund_amount FROM payment_ledger WHERE order_id = '" + line.orderId() + "'"))
                .as("the reservation became the refund")
                .isEqualTo("0");
        assertThat(scalar("commerce_db", "SELECT state FROM line_refund WHERE line_id = '" + line.lineId() + "'"))
                .isEqualTo("CONSUMED");
        assertThat(scalar(
                        "case_db",
                        "SELECT COUNT(*) FROM case_result_inbox WHERE operation_id = '" + operationId
                                + "' AND state = 'SUCCEEDED' AND disposition = 'ACCEPTED'"))
                .as("the recovered success reached the case as an accepted fact")
                .isEqualTo("1");
        assertThat(scalar(
                        "case_db",
                        "SELECT COUNT(*) FROM case_result_inbox WHERE operation_id = '" + operationId
                                + "' AND detail = 'duplicate delivery ignored'"))
                .as("and nothing in this run was a duplicate: the unknown and the recovered success are two"
                        + " different facts, delivered once each")
                .isEqualTo("0");
        assertThat(scalar(
                        "case_db",
                        "SELECT COUNT(*) FROM case_timeline WHERE case_id = '" + caseId + "' AND kind = 'CASE_CLOSED'"))
                .isEqualTo("1");
    }

    @Test
    @DisplayName("a command commerce refuses comes back to the case instead of leaving it executing")
    void theRefusedCommandComesBackToTheCase() throws Exception {
        // C05.3b. Before it, this ran to the same point and then stopped: commerce refused the command with a
        // WARN line and nothing else — a domain refusal is terminal for the transport, so the delivery was
        // acknowledged and gone — while the case had already written case_execution_command and consumed the
        // authorisation. It waited in EXECUTING for an answer that could not come. This is the same refusal the
        // driver hit twice by accident in C05.2c-3, now asked of the real chain on purpose.
        Assumptions.assumeTrue(
                !LINE_REFUSED.isBlank(),
                "the refusal run needs a line with no line_refund row (RESOLVEFLOW_E2E_LINE_REFUSED)");
        ApprovedCase run = driveToApproval(LINE_REFUSED);
        String caseId = run.caseId();

        // The case is pushed out of the approval state by the dispatch loop, refused by commerce, and told why —
        // three hops over the real broker, so the status is awaited rather than sampled once (C05.3a's lesson,
        // learned the hard way in C05.2c-4: asserting a state the system has not been given time to reach is
        // racing it).
        await(
                "the case is returned to a person",
                () -> "PENDING_REVIEW".equals(caseStatus(caseId)) ? "ok" : null,
                CHAIN_TIMEOUT);

        assertThat(scalar("case_db", "SELECT COUNT(*) FROM case_execution_command WHERE case_id = '" + caseId + "'"))
                .as("the case really did send a command; that is what made the silence a hole")
                .isEqualTo("1");
        assertThat(scalar(
                        "commerce_db", "SELECT COUNT(*) FROM refund_operation WHERE line_id = '" + LINE_REFUSED + "'"))
                .as("a refused command reserves nothing, so there is no operation to reconcile")
                .isEqualTo("0");

        String operationId =
                scalar("case_db", "SELECT operation_id FROM case_execution_command WHERE case_id = '" + caseId + "'");
        assertThat(operationId)
                .as("the answer has to be correlated through the operation id the case itself fixed")
                .isNotBlank();
        assertThat(scalar(
                        "case_db",
                        "SELECT COUNT(*) FROM case_result_inbox WHERE operation_id = '" + operationId
                                + "' AND event_type = 'RefundFailed' AND state = 'FAILED'"
                                + " AND disposition = 'ACCEPTED'"))
                .as("the case recorded why, which is the fact it never used to receive")
                .isEqualTo("1");
        assertThat(scalar(
                        "case_db",
                        "SELECT COUNT(*) FROM case_timeline WHERE case_id = '" + caseId + "' AND kind = 'CASE_CLOSED'"))
                .as("and nothing was closed: no refund happened, so there is no outcome to close on")
                .isEqualTo("0");
        assertThat(scalar("commerce_db", "SELECT COUNT(*) FROM line_refund WHERE line_id = '" + LINE_REFUSED + "'"))
                .as("the line still has no refund slot: the refusal did not create one")
                .isEqualTo("0");
    }

    // ------------------------------------------------------------------ the provider's lab surface

    /** Arm one fault for one operation. The provider refuses an unknown fault name, which is why this is checked. */
    private boolean armFault(String fault, String operationId) throws Exception {
        ObjectNode body = MAPPER.createObjectNode();
        body.put("fault", fault);
        body.put("operation_id", operationId);
        HttpResponse<String> response = HTTP.send(
                HttpRequest.newBuilder()
                        .uri(URI.create(PROVIDER_BASE + "/provider/v1/_lab/faults"))
                        .timeout(Duration.ofSeconds(10))
                        .header("Content-Type", "application/json")
                        .POST(HttpRequest.BodyPublishers.ofString(body.toString()))
                        .build(),
                HttpResponse.BodyHandlers.ofString());
        return response.statusCode() == 204;
    }

    private boolean clearFaults() throws Exception {
        HttpResponse<String> response = HTTP.send(
                HttpRequest.newBuilder()
                        .uri(URI.create(PROVIDER_BASE + "/provider/v1/_lab/faults"))
                        .timeout(Duration.ofSeconds(10))
                        .DELETE()
                        .build(),
                HttpResponse.BodyHandlers.ofString());
        return response.statusCode() == 204;
    }

    /** What the provider believes about one refund — the other side of the divergence. */
    private JsonNode providerRefund(String operationId) throws Exception {
        HttpResponse<String> response = HTTP.send(
                HttpRequest.newBuilder()
                        .uri(URI.create(PROVIDER_BASE + "/provider/v1/refunds/" + operationId))
                        .timeout(Duration.ofSeconds(10))
                        .GET()
                        .build(),
                HttpResponse.BodyHandlers.ofString());
        assertThat(response.statusCode())
                .as("the provider has a record of this refund: " + response.body())
                .isEqualTo(200);
        return MAPPER.readTree(response.body());
    }

    // ------------------------------------------------------------------ the three real entries

    /** One demo line's facts, read from the database rather than assumed. */
    private record LineFacts(String lineId, String merchant, String customer, String orderId, long amount) {}

    /** A case driven through all three entries up to the approval, with the line it was opened on. */
    private record ApprovedCase(LineFacts line, String caseId) {}

    /**
     * Read a line's facts, reset what a previous run may have left on it, and drive the three real entries.
     *
     * <p>Shared by both tests on purpose: "opened a case, delivered a proposal, got it approved" is not what
     * either of them is about, and a second copy of it would be a second place for the demo identities, the
     * citation or the reset to drift.
     */
    private ApprovedCase driveToApproval(String lineId) throws Exception {
        String merchant = scalar("commerce_db", "SELECT merchant_id FROM order_line WHERE line_id = '" + lineId + "'");
        String customer = scalar("commerce_db", "SELECT customer_id FROM order_line WHERE line_id = '" + lineId + "'");
        String orderId = scalar("commerce_db", "SELECT order_id FROM order_line WHERE line_id = '" + lineId + "'");
        long amount = Long.parseLong(
                scalar("commerce_db", "SELECT line_paid_amount FROM order_line WHERE line_id = '" + lineId + "'"));
        assertThat(merchant)
                .as("the demo line has to exist before anything can be driven")
                .isNotNull();
        LineFacts line = new LineFacts(lineId, merchant, customer, orderId, amount);

        // A line refund is per-order money: the driver reused this line before, and a run that started from
        // whatever the last run left behind would fail for reasons that are not about the chain. The reset is
        // the same one the module tests do in @BeforeEach, and it touches only this line and its order's ledger.
        assertThat(scalar(
                        "case_db",
                        "SELECT COUNT(*) FROM event_outbox WHERE status <> 'PUBLISHED' AND envelope LIKE '%" + lineId
                                + "%'"))
                .as("a command for this line that nobody delivered would reserve the slot before this run does,"
                        + " and the run would then fail for the previous run's reason")
                .isEqualTo("0");
        update(
                "commerce_db",
                "UPDATE line_refund SET state = 'FREE', operation_id = NULL, version = 1 WHERE line_id = '" + lineId
                        + "'");
        update(
                "commerce_db",
                "UPDATE payment_ledger SET refunded_amount = 0, reserved_refund_amount = 0, version = 1"
                        + " WHERE order_id = '" + orderId + "'");
        assertThat(scalar(
                        "commerce_db", "SELECT refunded_amount FROM payment_ledger WHERE order_id = '" + orderId + "'"))
                .isEqualTo("0");
        assertThat(scalar(
                        "case_db",
                        "SELECT COUNT(*) FROM aftersale_case WHERE line_id = '" + lineId + "' AND status NOT IN"
                                + " ('CLOSED_SUCCESS', 'CLOSED_REJECTED', 'CANCELLED')"))
                .as("this line has no case still open. Opening a second one is refused with CASE_ALREADY_OPEN —"
                        + " correctly — so saying so here keeps that refusal from looking like a chain failure."
                        + " Every seeded demo line already has an open case from the 2026-09-19 sessions, which"
                        + " is why the driver mints a line of its own rather than refunding a fixture line")
                .isEqualTo("0");

        String caseId = openCase(line);
        deliverProposal(caseId, line);

        String authorizationId =
                scalar("case_db", "SELECT authorization_id FROM case_authorization WHERE case_id = '" + caseId + "'");
        String caseVersion = scalar("case_db", "SELECT version FROM aftersale_case WHERE case_id = '" + caseId + "'");
        assertThat(authorizationId)
                .as("the proposal produced an authorisation for a reviewer to decide on")
                .isNotNull();
        approve(caseId, line.merchant(), caseVersion, authorizationId);
        return new ApprovedCase(line, caseId);
    }

    private String openCase(LineFacts line) throws Exception {
        ObjectNode body = MAPPER.createObjectNode();
        body.put("line_id", line.lineId());
        body.put("description", "承运商判定丢失，申请退款");
        body.putArray("requested_actions").add("REFUND");
        HttpResponse<String> response = post(
                "/api/v1/cases",
                token("demo-customer", line.merchant(), Role.CUSTOMER, line.customer()),
                "chain-case-" + UUID.randomUUID(),
                null,
                body);
        assertThat(response.statusCode())
                .as("opening a case through the public API: " + response.body())
                .isEqualTo(201);
        return MAPPER.readTree(response.body()).get("case_id").stringValue();
    }

    private void deliverProposal(String caseId, LineFacts line) throws Exception {
        ObjectNode proposal = MAPPER.createObjectNode();
        proposal.put("schema_version", 2);
        proposal.put("proposal_id", UUID.randomUUID().toString());
        proposal.put("run_id", UUID.randomUUID().toString());
        proposal.put("case_id", caseId);
        proposal.put("input_revision", 1);
        proposal.put("case_type", "LOGISTICS");
        proposal.put("recommended_action", "REFUND");
        proposal.put("summary", "承运商判定丢失，按政策全额退款");
        proposal.put("suggested_amount_minor", line.amount());
        proposal.putArray("reason_codes").add("CARRIER_LOST");
        proposal.putArray("policy_refs").add(citation(line.lineId()));

        ObjectNode body = MAPPER.createObjectNode();
        body.put("callback_id", "chain-proposal-" + UUID.randomUUID());
        body.put("run_id", proposal.get("run_id").stringValue());
        body.put("input_revision", 1);
        body.put("kind", "PROPOSAL");
        body.set("payload", proposal);
        body.put("traceparent", TRACEPARENT);
        HttpResponse<String> response = post(
                "/internal/v1/cases/" + caseId + "/agent-callbacks",
                new JwtCodec(JWT_SECRET, Duration.ofHours(1)).issueServiceToken("agent-service", Instant.now()),
                null,
                null,
                body);
        assertThat(response.statusCode())
                .as("delivering the proposal the Agent would deliver: " + response.body())
                .isEqualTo(200);
    }

    private void approve(String caseId, String merchant, String caseVersion, String authorizationId) throws Exception {
        String reviewerToken = token("demo-reviewer", merchant, Role.REVIEWER, null);
        HttpResponse<String> claimed = HTTP.send(
                HttpRequest.newBuilder()
                        .uri(URI.create(CASE_BASE + "/api/v1/cases/" + caseId + "/collaboration"))
                        .header("Authorization", "Bearer " + reviewerToken)
                        .header("Content-Type", "application/json")
                        .header("If-Collaboration-Match", "\"0\"")
                        .POST(HttpRequest.BodyPublishers.ofString("{\"action\":\"CLAIM\",\"reason\":\"合成链路：领取新建工单\"}"))
                        .build(),
                HttpResponse.BodyHandlers.ofString());
        assertThat(claimed.statusCode())
                .as("claim fresh chain case: " + claimed.body())
                .isEqualTo(200);
        long collaborationVersion =
                MAPPER.readTree(claimed.body()).get("version").longValue();
        ObjectNode body = MAPPER.createObjectNode();
        body.put("authorization_id", authorizationId);
        body.put("authorization_version", 1);
        body.put("decision", "APPROVE");
        body.put("reason", "物流结论与政策一致，证据充分");
        HttpResponse<String> response = HTTP.send(
                HttpRequest.newBuilder()
                        .uri(URI.create(CASE_BASE + "/api/v1/cases/" + caseId + "/reviews"))
                        .timeout(Duration.ofSeconds(30))
                        .header("Authorization", "Bearer " + reviewerToken)
                        .header("Content-Type", "application/json")
                        .header("If-Match", "\"" + caseVersion + "\"")
                        .header("If-Collaboration-Match", "\"" + collaborationVersion + "\"")
                        .POST(HttpRequest.BodyPublishers.ofString(body.toString()))
                        .build(),
                HttpResponse.BodyHandlers.ofString());
        assertThat(response.statusCode())
                .as("a reviewer approving: " + response.body())
                .isEqualTo(200);
    }

    /**
     * A citation for the rule the line's payment falls under.
     *
     * <p>Read from the imported bundles rather than written down: the approval re-checks the cited rule's hash,
     * so a citation this test invented would be refused for the right reason and would prove nothing about the
     * chain. The bundle is chosen by the line's payment time, which is the same rule policy selection uses.
     */
    private ObjectNode citation(String lineId) {
        String bundle = scalar(
                "case_db",
                "SELECT bundle_id FROM policy_bundle WHERE effective_from <= (SELECT paid_at FROM commerce_db.order_line"
                        + " WHERE line_id = '" + lineId + "') AND (effective_to IS NULL OR effective_to >"
                        + " (SELECT paid_at FROM commerce_db.order_line WHERE line_id = '" + lineId + "'))"
                        + " ORDER BY effective_from DESC LIMIT 1");
        String version = scalar("case_db", "SELECT version FROM policy_bundle WHERE bundle_id = '" + bundle + "'");
        assertThat(bundle)
                .as("the line's payment time has to fall inside an imported policy bundle, or no case can be opened")
                .isNotNull();

        String ruleId = scalar(
                "case_db",
                "SELECT rule_id FROM policy_rule WHERE bundle_id = '" + bundle + "' AND rule_id = 'R-LOST-001'");
        if (ruleId == null) {
            ruleId = scalar(
                    "case_db",
                    "SELECT rule_id FROM policy_rule WHERE bundle_id = '" + bundle + "' ORDER BY position LIMIT 1");
        }
        assertThat(ruleId).as("the bundle has at least one rule to cite").isNotNull();

        PolicyRule rule = null;
        try (Connection connection = connect("case_db");
                Statement statement = connection.createStatement();
                ResultSet rows =
                        statement.executeQuery("SELECT position, title, text FROM policy_rule WHERE bundle_id = '"
                                + bundle + "' AND rule_id = '" + ruleId + "'")) {
            assertThat(rows.next()).isTrue();
            rule = PolicyRule.from(
                    bundle, rows.getInt("position"), ruleId, rows.getString("title"), rows.getString("text"));
        } catch (SQLException problem) {
            throw new IllegalStateException("could not read the policy rule to cite", problem);
        }

        ObjectNode node = MAPPER.createObjectNode();
        node.put("bundle_id", bundle);
        node.put("version", version);
        node.put("rule_id", ruleId);
        node.put("chunk_id", rule.chunkId());
        node.put("content_hash", rule.contentHash());
        return node;
    }

    // ------------------------------------------------------------------ talking to the running service

    private HttpResponse<String> post(String path, String token, String idempotencyKey, String ifMatch, JsonNode body)
            throws Exception {
        HttpRequest.Builder request = HttpRequest.newBuilder()
                .uri(URI.create(CASE_BASE + path))
                .timeout(Duration.ofSeconds(30))
                .header("Authorization", "Bearer " + token)
                .header("Content-Type", "application/json")
                .POST(HttpRequest.BodyPublishers.ofString(body.toString()));
        if (idempotencyKey != null) {
            request.header("Idempotency-Key", idempotencyKey);
        }
        if (ifMatch != null) {
            request.header("If-Match", ifMatch);
        }
        return HTTP.send(request.build(), HttpResponse.BodyHandlers.ofString());
    }

    private String token(String subject, String merchant, Role role, String customerId) {
        return new JwtCodec(JWT_SECRET, Duration.ofHours(1))
                .issue(new AuthenticatedPrincipal(subject, merchant, role, customerId), Instant.now());
    }

    private String caseStatus(String caseId) {
        return scalar("case_db", "SELECT status FROM aftersale_case WHERE case_id = '" + caseId + "'");
    }

    private String operationState(String operationId) {
        return scalar("commerce_db", "SELECT state FROM refund_operation WHERE operation_id = '" + operationId + "'");
    }

    // ------------------------------------------------------------------ polling and raw reads

    /** Wait for a condition, and fail with the sentence that says what never happened. */
    private static String await(String description, java.util.function.Supplier<String> probe, Duration timeout) {
        Instant deadline = Instant.now().plus(timeout);
        String last = null;
        while (Instant.now().isBefore(deadline)) {
            last = probe.get();
            if (last != null) {
                return last;
            }
            try {
                Thread.sleep(250);
            } catch (InterruptedException interrupted) {
                Thread.currentThread().interrupt();
                throw new IllegalStateException("interrupted while waiting for: " + description, interrupted);
            }
        }
        throw new AssertionError("timed out after " + timeout.toSeconds() + "s waiting for: " + description
                + " (last observed: " + last + ")");
    }

    private static Connection connect(String database) throws SQLException {
        return DriverManager.getConnection(
                "jdbc:mysql://" + MYSQL_HOST + ":3306/" + database
                        + "?connectionTimeZone=UTC&preserveInstants=true&allowPublicKeyRetrieval=true&useSSL=false",
                "root",
                MYSQL_ROOT_PASSWORD);
    }

    private static String scalar(String database, String statement) {
        List<String> values = row(database, statement);
        return values.isEmpty() || values.get(0) == null || "NULL".equals(values.get(0)) ? null : values.get(0);
    }

    private static List<String> row(String database, String statement) {
        try (Connection connection = connect(database);
                Statement query = connection.createStatement();
                ResultSet rows = query.executeQuery(statement)) {
            if (!rows.next()) {
                return List.of();
            }
            List<String> values = new ArrayList<>();
            for (int column = 1; column <= rows.getMetaData().getColumnCount(); column++) {
                values.add(String.valueOf(rows.getString(column)));
            }
            return values;
        } catch (SQLException problem) {
            throw new IllegalStateException("could not read " + database + ": " + problem.getMessage(), problem);
        }
    }

    private static void update(String database, String statement) {
        try (Connection connection = connect(database);
                Statement update = connection.createStatement()) {
            update.executeUpdate(statement);
        } catch (SQLException problem) {
            throw new IllegalStateException("could not write " + database + ": " + problem.getMessage(), problem);
        }
    }

    private static String env(String name, String fallback) {
        String value = System.getenv(name);
        return value == null || value.isBlank() ? fallback : value;
    }
}
