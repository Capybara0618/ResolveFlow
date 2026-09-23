package com.resolveflow.caseservice.outbox;

import static org.assertj.core.api.Assertions.assertThat;

import com.resolveflow.caseservice.casefile.ExecutableAction;
import com.resolveflow.caseservice.casefile.RefundCommand;
import com.resolveflow.shared.core.CoreEnvelope;
import com.resolveflow.shared.core.CoreEventSignature;
import java.security.PublicKey;
import java.time.Duration;
import java.time.Instant;
import java.util.UUID;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.condition.EnabledIfEnvironmentVariable;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.jdbc.core.JdbcTemplate;
import tools.jackson.databind.JsonNode;
import tools.jackson.databind.ObjectMapper;

/**
 * C05.1c: the command over the real broker, not over a publisher a test controls.
 *
 * <p>{@link CaseEventOutboxApiTest} proves the outbox's behaviour against a recording publisher and a
 * Testcontainers MySQL. That is the right way to test delivery logic, and it says nothing about whether the
 * RocketMQ client, the compose broker, the topic and the running commerce-service agree with each other. This
 * test is the other half: it runs the real publisher against {@code 127.0.0.1:9876} and the real
 * {@code case_db}, and the {@code commerce-service} process that the driver script started alongside it is
 * what turns those published bytes into a reservation.
 *
 * <p>It is opt-in, and by environment variable rather than by system property: the default suite must stay
 * runnable with no broker (docs/engineering.md, {@code -Suite all-offline}), and Maven does not promise to
 * forward {@code -D} values to the forked test JVM the way it does the environment.
 *
 * <p><b>What it does to the outside world, deliberately.</b> It writes one real outbox row and publishes
 * three real messages. The row is not deleted afterwards: the row is the evidence, and a suite that erased
 * its own proof would be the same mistake as a delivery loop that deletes an event it gave up on. The
 * duplicate and the tampered copy are published directly through {@link EventPublisher} rather than written
 * as new outbox rows, because those two are exactly what a transport does — deliver the same bytes twice,
 * and deliver bytes that no longer match their signature. Neither is something case-service would originate,
 * which is the point: the consumer has to survive both.
 */
@SpringBootTest(
        properties = {
            "resolveflow.events.publisher.enabled=true",
            "resolveflow.events.outbox.delivery-enabled=true",
            "resolveflow.events.namesrv=127.0.0.1:9876",
            // Faster than the production default: the test is waiting for one pass, not running a service.
            "resolveflow.events.outbox.poll-interval-ms=300",
            // A transient refusal (broker still electing, topic being created) should cost a second, not five.
            "resolveflow.events.outbox.retry-base-seconds=1"
        })
@EnabledIfEnvironmentVariable(named = "RESOLVEFLOW_E2E_BROKER", matches = "true")
class CoreEventTransportSystemTest {

    private static final Logger LOG = LoggerFactory.getLogger(CoreEventTransportSystemTest.class);
    private static final ObjectMapper MAPPER = new ObjectMapper();
    private static final String TRACEPARENT = "00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01";
    private static final Duration PUBLISH_TIMEOUT = Duration.ofSeconds(30);

    @Autowired
    EventOutbox outbox;

    @Autowired
    OutboxRepository outboxRepository;

    @Autowired
    EventPublisher publisher;

    @Autowired
    JdbcTemplate jdbc;

    @Test
    @DisplayName("a command written by the outbox reaches the broker, and a redelivery and a tampered copy follow it")
    void theCommandReachesTheBroker() throws Exception {
        String operationId =
                env("RESOLVEFLOW_E2E_OPERATION_ID", UUID.randomUUID().toString());
        String caseId = env("RESOLVEFLOW_E2E_CASE_ID", UUID.randomUUID().toString());
        String authorizationId =
                env("RESOLVEFLOW_E2E_AUTHORIZATION_ID", UUID.randomUUID().toString());
        String poisonEventId =
                env("RESOLVEFLOW_E2E_POISON_EVENT_ID", UUID.randomUUID().toString());
        String merchantId = env("RESOLVEFLOW_E2E_MERCHANT", "M-1001");
        String lineId = env("RESOLVEFLOW_E2E_LINE_ID", "7001");
        long amountMinor = Long.parseLong(env("RESOLVEFLOW_E2E_AMOUNT_MINOR", "2599"));

        RefundCommand command = new RefundCommand(
                operationId,
                caseId,
                authorizationId,
                2,
                lineId,
                merchantId,
                ExecutableAction.REFUND,
                2,
                "CNY",
                amountMinor,
                "2026.09");

        String eventId = outbox.writeRefundCommand(
                command.caseId(), command.authorizationId(), merchantId, command, TRACEPARENT);
        LOG.info("C051C-WRITTEN event_id={} operation_id={}", eventId, operationId);

        OutboxEvent published = awaitPublished(eventId);
        assertThat(published.attempts())
                .as("one attempt reached the broker and was acknowledged")
                .isEqualTo(1);
        assertThat(published.lastError())
                .as("a published event carries no failure, because none happened")
                .isNull();
        assertThat(published.topic()).isEqualTo(CoreEnvelope.CASE_TOPIC);
        assertThat(published.producer()).isEqualTo(CoreEnvelope.CASE_SERVICE);
        LOG.info(
                "C051C-PUBLISHED event_id={} attempts={} at={}",
                eventId,
                published.attempts(),
                published.publishedAt());

        // What the broker was handed is what was signed: asserted here rather than assumed, because the row
        // could have been published from a re-rendered copy and nothing downstream would say so.
        JsonNode envelope = MAPPER.readTree(published.envelope());
        CoreEventSignature.verify(envelope, published.signature(), trustedPublicKey());
        assertThat(CoreEnvelope.canonical(envelope))
                .as("the published bytes are exactly the stored envelope")
                .isEqualTo(published.envelope());

        // A redelivery: the same bytes, a second time. At-least-once means this will happen for real, and the
        // consumer's inbox is what has to make it harmless.
        publisher.publish(published.topic(), published.envelope(), eventId);
        LOG.info("C051C-DUPLICATE event_id={} (identical bytes republished)", eventId);

        // CF1 (docs/evaluation.md:34): "the send happened but the record of it did not". A crash between the
        // broker's acknowledgement and markPublished leaves exactly this row — still PENDING, already
        // delivered — and the loop's next pass sends it again. The state is created with one UPDATE rather
        // than by killing the JVM mid-publish, because no test can time that reliably; everything after the
        // UPDATE is the real path, and the duplicate it produces is real too.
        int requeued = jdbc.update(
                "UPDATE event_outbox SET status = 'PENDING', published_at = NULL"
                        + " WHERE event_id = ? AND status = 'PUBLISHED'",
                eventId);
        assertThat(requeued)
                .as("the delivered-but-unrecorded state CF1 describes")
                .isEqualTo(1);

        OutboxEvent republished = awaitPublished(eventId);
        assertThat(republished.attempts())
                .as("the loop really sent it again, rather than deciding it was already done")
                .isEqualTo(2);
        LOG.info("C051C-REQUEUED event_id={} attempts={}", eventId, republished.attempts());

        // A message whose signature no longer covers it, published from the same producer. The broker has no
        // opinion about signatures, which is why this arrives at the consumer at all; refusing it is the
        // consumer's job, and the driver asserts it refused, filed the refusal and moved no money.
        String tampered = tamper(published.envelope(), amountMinor, eventId, poisonEventId);
        publisher.publish(published.topic(), tampered, poisonEventId);
        LOG.info("C051C-POISON event_id={} (signature no longer covers the document)", poisonEventId);
    }

    /**
     * The same document with the money changed and a different event id.
     *
     * <p>Text rather than a re-rendered tree on purpose: the point is a document that was signed and then
     * altered, and rendering it again through the canonicaliser would produce the very "what the code looks
     * like now" that the stored-envelope design exists to avoid. Both forms of the member are tried so the
     * test fails loudly on a canonicaliser change instead of quietly publishing a valid command.
     */
    private static String tamper(String envelope, long amountMinor, String eventId, String poisonEventId) {
        String altered = envelope.replace("\"amount_minor\":" + amountMinor, "\"amount_minor\":1");
        if (altered.equals(envelope)) {
            altered = envelope.replace(String.valueOf(amountMinor), "1");
        }
        altered = altered.replace(eventId, poisonEventId);
        assertThat(altered).as("the tamper has to actually change the document").isNotEqualTo(envelope);
        return altered;
    }

    private OutboxEvent awaitPublished(String eventId) throws InterruptedException {
        Instant deadline = Instant.now().plus(PUBLISH_TIMEOUT);
        OutboxEvent current = null;
        while (Instant.now().isBefore(deadline)) {
            current = outboxRepository.find(eventId);
            if (current != null && current.isPublished()) {
                return current;
            }
            Thread.sleep(250);
        }
        throw new AssertionError("event " + eventId + " was not published within " + PUBLISH_TIMEOUT
                + "; last seen: "
                + (current == null
                        ? "no row"
                        : current.status() + " attempts=" + current.attempts() + " error=" + current.lastError()));
    }

    private static PublicKey trustedPublicKey() {
        return CoreEnvelope.publicKeyFromSpkiBase64(com.resolveflow.shared.core.CoreFixtures.publicKeySpkiBase64());
    }

    private static String env(String name, String fallback) {
        String value = System.getenv(name);
        return value == null || value.isBlank() ? fallback : value;
    }
}
