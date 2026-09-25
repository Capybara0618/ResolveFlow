package com.resolveflow.caseservice.casefile;

import static org.assertj.core.api.Assertions.assertThat;

import com.resolveflow.caseservice.CaseDatabaseTest;
import com.resolveflow.shared.security.JwtCodec;
import java.time.Duration;
import java.time.Instant;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.boot.resttestclient.autoconfigure.AutoConfigureRestTestClient;
import org.springframework.boot.test.context.TestConfiguration;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Primary;
import org.springframework.test.context.TestPropertySource;
import org.springframework.test.web.servlet.client.RestTestClient;
import tools.jackson.databind.ObjectMapper;

/**
 * C06.3a: the resident dispatch loop, and why the case write does not do the sending itself.
 *
 * <p>C06.1c left the dispatch as a method nobody called: a case opened by a real user still had to wait
 * for a test to call {@code dispatchDue}. This class pins the two halves of the fix, and they are different
 * promises:
 *
 * <ol>
 *   <li><b>Opening a case never depends on the Agent.</b> The binding is committed with the case, and the
 *       create request returns 201 with the Agent switched off entirely. This is the property that keeps an
 *       Agent outage from looking like "the customer cannot file a refund" — and the reason the send cannot
 *       live in the create transaction.
 *   <li><b>The loop is what delivers.</b> With the loop on and nobody calling anything, the run reaches the
 *       Agent on its own.
 * </ol>
 *
 * <p>The loop is switched on by the property the rest of this service already uses for the execution
 * dispatch loop ({@code resolveflow.dispatch.enabled}), so a running service that dispatches authorisations
 * dispatches runs too, and no existing harness has to learn a second switch. Off is still the default: a
 * service that was never asked to dispatch leaves the binding PENDING, which is the honest state.
 */
@AutoConfigureRestTestClient
@TestPropertySource(
        properties = {
            "resolveflow.dispatch.enabled=true",
            "resolveflow.dispatch.poll-interval-ms=100",
            "resolveflow.dispatch.batch-size=10"
        })
class AgentRunDispatchLoopApiTest extends CaseDatabaseTest {

    private static final ObjectMapper MAPPER = new ObjectMapper();

    @TestConfiguration
    static class StubConfiguration {

        @Bean
        @Primary
        StubCommerce commerceStub(
                org.springframework.web.client.RestClient.Builder builder,
                @Value("${resolveflow.identity.jwt.secret}") String secret,
                @Value("${resolveflow.identity.jwt.service-token-ttl:PT1H}") Duration ttl) {
            return new StubCommerce(builder, new JwtCodec(secret, ttl));
        }

        @Bean
        @Primary
        StubAgent agentStub(
                org.springframework.web.client.RestClient.Builder builder,
                @Value("${resolveflow.identity.jwt.secret}") String secret,
                @Value("${resolveflow.identity.jwt.service-token-ttl:PT1H}") Duration ttl) {
            return new StubAgent(builder, new JwtCodec(secret, ttl));
        }
    }

    @Autowired
    RestTestClient rest;

    @Autowired
    StubAgent agent;

    @Autowired
    AgentRunDispatchLoop loop;

    @Autowired
    JwtCodec jwtCodec;

    private long lineCounter = 7800;

    @BeforeEach
    void prepare() {
        deleteAllCaseData(jdbc);
        agent.reset();
    }

    private String userToken() {
        return jwtCodec.issue(
                new com.resolveflow.shared.security.AuthenticatedPrincipal(
                        "demo-customer", "M-1001", com.resolveflow.shared.security.Role.CUSTOMER, "C-2002"),
                Instant.now());
    }

    /** Opens a case and returns its id. */
    private String openCase() {
        String body = rest.post()
                .uri("/api/v1/cases")
                .header("Authorization", "Bearer " + userToken())
                .header("Idempotency-Key", "loop-case-" + (++lineCounter))
                .contentType(org.springframework.http.MediaType.APPLICATION_JSON)
                .body("{\"line_id\":\"" + lineCounter + "\",\"description\":\"退款诉求\","
                        + "\"requested_actions\":[\"REFUND\"]}")
                .exchange()
                .expectStatus()
                .isCreated()
                .expectBody(String.class)
                .returnResult()
                .getResponseBody();
        return MAPPER.readTree(body).get("case_id").stringValue();
    }

    /**
     * Wait for a fact the loop produces on its own.
     *
     * <p>A poll rather than a fixed sleep followed by one assertion: the loop's tick boundary is not
     * something this test controls, so a fixed sleep is either slower than necessary or flaky. The project
     * has no awaitility dependency and three waits do not justify adding one.
     */
    private static void awaitUntil(String what, java.util.function.BooleanSupplier fact) {
        Instant limit = Instant.now().plus(Duration.ofSeconds(10));
        while (Instant.now().isBefore(limit)) {
            if (fact.getAsBoolean()) {
                return;
            }
            try {
                Thread.sleep(50);
            } catch (InterruptedException interrupted) {
                Thread.currentThread().interrupt();
                throw new IllegalStateException("interrupted while waiting for " + what, interrupted);
            }
        }
        throw new AssertionError("timed out waiting for " + what);
    }

    private String dispatchStatus(String caseId) {
        return jdbc.queryForObject("SELECT dispatch_status FROM agent_binding WHERE case_id = ?", String.class, caseId);
    }

    @Test
    @DisplayName("the loop delivers a run by itself, with nobody calling anything")
    void theLoopDeliversOnItsOwn() {
        String caseId = openCase();

        // Nothing in this test calls the dispatch. If the run arrives, the resident loop is what sent it.
        awaitUntil("the loop to deliver the run", () -> agent.dispatched.size() == 1);

        assertThat(agent.dispatched.get(0).get("case_id").stringValue()).isEqualTo(caseId);
        assertThat(dispatchStatus(caseId)).isEqualTo("DISPATCHED");
    }

    @Test
    @DisplayName("a failing send does not stop the loop: the next tick delivers the same binding")
    void aFailedSendIsRetriedByTheNextTick() {
        // Armed BEFORE the case exists. The loop polls the table, not this test, so setting the flag after
        // openCase() would be a race it wins about half the time — and the failing run would then be a
        // delivered one.
        agent.failNext = true;
        String caseId = openCase();

        // The first tick fails. The loop must not give up on the row, and it must not stamp it delivered.
        awaitUntil("the first tick to fail", () -> agent.failures.get() >= 1);
        assertThat(dispatchStatus(caseId)).isEqualTo("PENDING");

        // And then it succeeds on a later tick, without anybody intervening.
        awaitUntil("a later tick to deliver the run", () -> agent.dispatched.size() == 1);
        assertThat(dispatchStatus(caseId)).isEqualTo("DISPATCHED");
    }

    @Test
    @DisplayName("the loop gives up on nothing: a binding the Agent keeps refusing is still retried")
    void aRefusedBindingIsStillRetried() {
        agent.refuseEverySend = true;
        String caseId = openCase();

        // A 4xx is the Agent saying the request itself is wrong. It is logged as a failure, but the row
        // stays PENDING rather than being marked delivered — a case silently recorded as dispatching while
        // the Agent never accepted it is exactly the state nobody can debug later.
        awaitUntil("the loop to keep trying a refused run", () -> agent.failures.get() >= 2);
        assertThat(dispatchStatus(caseId)).isEqualTo("PENDING");
        assertThat(agent.dispatched).isEmpty();
    }

    @Test
    @DisplayName("the loop is a separate bean, so it can be switched off without losing the act")
    void theLoopIsSwitchedOnHere() {
        // This asserts the wiring rather than the behaviour: the class is conditional on the property, and
        // the property is on in this context. A loop that was never created would make the tests above pass
        // for the wrong reason on a machine where something else dispatched.
        assertThat(loop).isNotNull();
    }
}
