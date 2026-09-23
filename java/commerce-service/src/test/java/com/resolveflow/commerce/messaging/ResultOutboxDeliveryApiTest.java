package com.resolveflow.commerce.messaging;

import static org.assertj.core.api.Assertions.assertThat;

import com.resolveflow.commerce.CommerceDatabaseTest;
import java.time.Instant;
import java.util.ArrayList;
import java.util.List;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.TestConfiguration;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Primary;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.test.context.TestPropertySource;

/**
 * Handing the results the case is owed to the transport, at least once (C05.2b, docs/core-contracts.md:67).
 *
 * <p>What is under test is the delivery state machine, and it is tested with a stub transport because that is
 * the only way the failure paths can be exercised at all: a broker that is down, a result that keeps failing
 * until the service gives up, and a published result that must not go out twice. The claims are:
 *
 * <ul>
 *   <li><b>The stored bytes are what travels.</b> The body handed to the transport is the stored envelope,
 *       unchanged, and the topic is the protocol's own ({@code rf.commerce.core.v2}) — the transport derives the
 *       broker name, not this service.
 *   <li><b>A failed attempt keeps the result and waits.</b> The row stays {@code PENDING}, records the error,
 *       and is not attempted again until its backoff has elapsed — a pass that finds nothing due reports no work
 *       rather than a success (docs/engineering.md:56).
 *   <li><b>Giving up keeps the row.</b> After {@code max-attempts} the result is {@code DEAD} and still there
 *       with its envelope intact: the case never heard the outcome, and that fact is what an operator replays
 *       from.
 *   <li><b>Published is final.</b> A delivered result is never offered again.
 * </ul>
 *
 * <p>The envelope seeded here is a stand-in on purpose. Its shape, its signature and the operation version it
 * carries are {@link com.resolveflow.commerce.refund.RefundAcceptanceApiTest}'s subject, checked there against
 * the contract's own frozen expectations; what this class is about is bytes and delivery state, and mixing the
 * two subjects into one test is how a failure stops saying which of them broke.
 */
@TestPropertySource(
        properties = {
            // Two attempts, so "gives up" is reachable in a test; and a long backoff, so the retry that follows a
            // failure is provably *not* due yet rather than racing the clock.
            "resolveflow.events.outbox.max-attempts=2",
            "resolveflow.events.outbox.retry-base-seconds=300"
        })
class ResultOutboxDeliveryApiTest extends CommerceDatabaseTest {

    private static final String EVENT_ID = "8f8f8f8f-1111-4222-8333-444455556666";
    private static final String TOPIC = "rf.commerce.core.v2";

    /** Stand-in bytes: this class is about what happens to a document, not about what it says. */
    private static final String ENVELOPE =
            "{\"event_type\":\"RefundSucceeded\",\"schema_version\":2,\"payload\":{\"state\":\"SUCCEEDED\"}}";

    @Autowired
    ResultOutboxRepository outbox;

    @Autowired
    ResultOutboxDeliveryService delivery;

    @Autowired
    RecordingPublisher publisher;

    @Autowired
    JdbcTemplate jdbc;

    @BeforeEach
    void seedOnePendingResult() {
        jdbc.execute("DELETE FROM event_outbox");
        publisher.reset();
        // Written through the production statement, so the seed cannot drift from the way a real result lands
        // (and so the timestamps go through the same conversion the delivery query will use).
        outbox.insert(
                EVENT_ID,
                "RefundSucceeded",
                2,
                "M-1001",
                TOPIC,
                "commerce-service",
                ENVELOPE,
                "sig-bytes",
                "commerce-service-demo-key",
                Instant.now());
    }

    @Test
    @DisplayName("a result is handed over once, with the topic and the bytes it was stored with")
    void aResultIsHandedOverOnce() {
        assertThat(delivery.deliverDue(10)).isEqualTo(new ResultOutboxDeliveryService.Pass(1, 0, 0));

        assertThat(publisher.topics).containsExactly(TOPIC);
        assertThat(publisher.bodies).containsExactly(ENVELOPE);
        ResultOutboxRepository.ResultEvent row = outbox.find(EVENT_ID);
        assertThat(row.status()).isEqualTo("PUBLISHED");
        assertThat(row.attempts()).isEqualTo(1);
        assertThat(row.publishedAt()).isNotNull();
        assertThat(row.nextAttemptAt()).isNull();

        assertThat(delivery.deliverDue(10))
                .as("published is final: nothing is offered twice")
                .isEqualTo(new ResultOutboxDeliveryService.Pass(0, 0, 0));
        assertThat(publisher.bodies).hasSize(1);
    }

    @Test
    @DisplayName("a transport that is down leaves the result to try again, and the retry waits its backoff")
    void aFailedAttemptIsKeptAndWaits() {
        publisher.fail = new PublishException("broker is down");

        assertThat(delivery.deliverDue(10)).isEqualTo(new ResultOutboxDeliveryService.Pass(0, 1, 0));
        ResultOutboxRepository.ResultEvent row = outbox.find(EVENT_ID);
        assertThat(row.status())
                .as("the outcome is not delivered, and is not lost either")
                .isEqualTo("PENDING");
        assertThat(row.attempts()).isEqualTo(1);
        assertThat(row.lastError()).isEqualTo("broker is down");
        assertThat(row.envelope()).isEqualTo(ENVELOPE);
        assertThat(row.nextAttemptAt()).isAfter(Instant.now());

        assertThat(delivery.deliverDue(10))
                .as("not due yet, so the pass attempted nothing: no success is reported for work not done")
                .isEqualTo(new ResultOutboxDeliveryService.Pass(0, 0, 0));
        assertThat(publisher.bodies)
                .as("and the transport was not called again either")
                .hasSize(1);
    }

    @Test
    @DisplayName("a result that keeps failing is given up on, and the row it leaves is kept")
    void aResultThatKeepsFailingIsGivenUpOn() {
        publisher.fail = new PublishException("broker is down");
        assertThat(delivery.deliverDue(10)).isEqualTo(new ResultOutboxDeliveryService.Pass(0, 1, 0));

        // The wait elapsed, which in production is the backoff running out and here is one statement.
        jdbc.update("UPDATE event_outbox SET next_attempt_at = NULL WHERE event_id = ?", EVENT_ID);

        assertThat(delivery.deliverDue(10))
                .as("max-attempts is 2 in this test, so the second failure is the last one")
                .isEqualTo(new ResultOutboxDeliveryService.Pass(0, 0, 1));
        ResultOutboxRepository.ResultEvent dead = outbox.find(EVENT_ID);
        assertThat(dead.status()).isEqualTo("DEAD");
        assertThat(dead.attempts()).isEqualTo(2);
        assertThat(dead.lastError()).isEqualTo("broker is down");
        assertThat(dead.envelope())
                .as("giving up keeps the event: the row is what a manual replay would start from")
                .isEqualTo(ENVELOPE);
        assertThat(outbox.countByStatus("DEAD")).isEqualTo(1);

        assertThat(delivery.deliverDue(10))
                .as("a dead result is not retried by the loop")
                .isEqualTo(new ResultOutboxDeliveryService.Pass(0, 0, 0));
        assertThat(publisher.bodies).hasSize(2);
    }

    /** A transport that records what it was handed, and fails on demand. */
    static final class RecordingPublisher implements EventPublisher {

        final List<String> topics = new ArrayList<>();
        final List<String> bodies = new ArrayList<>();
        RuntimeException fail;

        @Override
        public void publish(String topic, String envelope, String eventId) {
            topics.add(topic);
            bodies.add(envelope);
            if (fail != null) {
                throw fail;
            }
        }

        void reset() {
            topics.clear();
            bodies.clear();
            fail = null;
        }
    }

    @TestConfiguration
    static class StubTransport {

        /**
         * The publisher this context uses. {@code @Primary} because the production default
         * ({@code MessagingConfiguration.NoTransportConfigured}) also exists and refuses everything: a test must
         * not depend on bean-registration order to decide which one delivers.
         */
        @Bean
        @Primary
        RecordingPublisher recordingPublisher() {
            return new RecordingPublisher();
        }
    }
}
