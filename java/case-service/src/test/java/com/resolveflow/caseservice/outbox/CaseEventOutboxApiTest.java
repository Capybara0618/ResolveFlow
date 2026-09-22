package com.resolveflow.caseservice.outbox;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

import com.resolveflow.caseservice.CaseDatabaseTest;
import com.resolveflow.caseservice.casefile.ExecutableAction;
import com.resolveflow.caseservice.casefile.RefundCommand;
import com.resolveflow.shared.core.CoreEnvelope;
import com.resolveflow.shared.core.CoreEventSignature;
import java.security.PublicKey;
import java.time.Clock;
import java.time.Duration;
import java.time.Instant;
import java.util.ArrayList;
import java.util.List;
import java.util.UUID;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.boot.test.context.TestConfiguration;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Primary;
import tools.jackson.databind.JsonNode;
import tools.jackson.databind.ObjectMapper;
import tools.jackson.databind.node.ObjectNode;

/**
 * The signed outbox (C05.1a, docs/domain-model.md:45, docs/core-contracts.md:67).
 *
 * <p>The properties under test are the ones that make the outbox worth having:
 *
 * <ul>
 *   <li><b>It is written in the deciding transaction.</b> An event that committed while its effect rolled back
 *       would announce something that did not happen.
 *   <li><b>What is stored is what was signed.</b> The consumer verifies the bytes the producer signed, so the
 *       row carries the finished envelope rather than a model to re-render later.
 *   <li><b>The signature covers the envelope, not just the payload.</b> Re-addressing a message to another
 *       topic, or claiming another producer, has to invalidate it.
 *   <li><b>Delivery is at least once and never gives up quietly.</b> A failure keeps the row and schedules
 *       another attempt; attempts exhausted keeps the row as DEAD rather than deleting the evidence.
 * </ul>
 */
class CaseEventOutboxApiTest extends CaseDatabaseTest {

    private static final ObjectMapper MAPPER = new ObjectMapper();
    private static final String MERCHANT = "M-1001";

    /** A publisher a test controls, which is what makes delivery behaviour observable at all. */
    static final class RecordingPublisher implements EventPublisher {

        final List<String> published = new ArrayList<>();

        int failuresRemaining;

        String lastError = "broker refused";

        @Override
        public void publish(String topic, String envelope, String eventId) {
            if (failuresRemaining > 0) {
                failuresRemaining--;
                throw new PublishException(lastError);
            }
            published.add(topic + ":" + eventId);
        }
    }

    @TestConfiguration
    static class PublisherConfiguration {

        @Bean
        @Primary
        RecordingPublisher recordingPublisher() {
            return new RecordingPublisher();
        }
    }

    @Autowired
    EventOutbox outbox;

    @Autowired
    OutboxRepository outboxRepository;

    @Autowired
    OutboxDeliveryService delivery;

    @Autowired
    RecordingPublisher publisher;

    @Autowired
    org.springframework.transaction.support.TransactionTemplate transactions;

    @Value("${resolveflow.events.private-key-pkcs8-base64:}")
    String configuredKey;

    @BeforeEach
    void clearOutbox() {
        publisher.published.clear();
        publisher.failuresRemaining = 0;
        // The outbox is a child of the case tables, so it goes first; deleteAllCaseData owns the order for the
        // case tables themselves.
        jdbc.execute("DELETE FROM case_execution_command");
        jdbc.execute("DELETE FROM event_outbox");
        deleteAllCaseData(jdbc);
        publisher.published.clear();
        publisher.failuresRemaining = 0;
    }

    private RefundCommand command() {
        return new RefundCommand(
                UUID.randomUUID().toString(),
                UUID.randomUUID().toString(),
                UUID.randomUUID().toString(),
                2,
                "7001",
                MERCHANT,
                ExecutableAction.REFUND,
                2,
                "CNY",
                2599,
                "2026.09");
    }

    private String writeCommand() {
        RefundCommand command = command();
        return outbox.writeRefundCommand(command.caseId(), command.authorizationId(), MERCHANT, command, traceparent());
    }

    private static String traceparent() {
        return "00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01";
    }

    private static PublicKey trustedPublicKey() {
        return CoreEnvelope.publicKeyFromSpkiBase64(com.resolveflow.shared.core.CoreFixtures.publicKeySpkiBase64());
    }

    @Test
    @DisplayName("a written event is a signed, canonical core envelope with the right producer and topic")
    void aWrittenEventIsASignedCoreEnvelope() {
        String eventId = writeCommand();

        OutboxEvent stored = outboxRepository.find(eventId);

        assertThat(stored.status()).isEqualTo("PENDING");
        assertThat(stored.attempts()).isZero();
        assertThat(stored.publishedAt()).isNull();
        assertThat(stored.eventType()).isEqualTo(CoreEnvelope.REFUND_REQUESTED);
        assertThat(stored.producer()).as("a command comes from case-service").isEqualTo(CoreEnvelope.CASE_SERVICE);
        assertThat(stored.topic()).isEqualTo(CoreEnvelope.CASE_TOPIC);
        assertThat(stored.schemaVersion()).isEqualTo(2);
        assertThat(stored.signingKeyId()).isNotBlank();
        assertThat(stored.signature()).isNotBlank();

        JsonNode envelope = MAPPER.readTree(stored.envelope());
        assertThat(CoreEnvelope.canonical(envelope))
                .as("the stored document is exactly what was signed, not a re-rendering")
                .isEqualTo(stored.envelope());
        assertThat(envelope.get("signature").stringValue()).isEqualTo(stored.signature());
        CoreEventSignature.verify(envelope, stored.signature(), trustedPublicKey());

        JsonNode payload = envelope.get("payload");
        assertThat(payload.get("amount_minor").asLong()).isEqualTo(2599);
        assertThat(payload.get("quantity").asInt()).isEqualTo(2);
        assertThat(payload.get("action").stringValue()).isEqualTo("REFUND");
        assertThat(payload.get("target_service").stringValue()).isEqualTo("commerce-service");
        assertThat(payload.get("payload_hash").stringValue())
                .as("the command carries the hash its consumer re-derives")
                .hasSize(64);
        assertThat(envelope.get("causation_id").stringValue())
                .as("the command names the authorisation it came from")
                .isEqualTo(payload.get("authorization_id").stringValue());
        assertThat(envelope.get("traceparent").stringValue()).isEqualTo(traceparent());
    }

    @Test
    @DisplayName("the signature covers the envelope, so re-addressing or re-attributing it is caught")
    void theSignatureCoversMoreThanThePayload() {
        String eventId = writeCommand();
        OutboxEvent stored = outboxRepository.find(eventId);

        // The payload is untouched in both cases: only the routing members change. A signature that covered
        // the payload alone would accept both, and a message could then be delivered to a topic nobody
        // expects from a producer that never sent it.
        ObjectNode readdressed = (ObjectNode) MAPPER.readTree(stored.envelope());
        readdressed.put("topic", CoreEnvelope.COMMERCE_TOPIC);
        assertThatThrownBy(() -> CoreEventSignature.verify(readdressed, stored.signature(), trustedPublicKey()))
                .isInstanceOf(CoreEventSignature.CoreSignatureException.class);

        ObjectNode reattributed = (ObjectNode) MAPPER.readTree(stored.envelope());
        reattributed.put("producer", CoreEnvelope.COMMERCE_SERVICE);
        assertThatThrownBy(() -> CoreEventSignature.verify(reattributed, stored.signature(), trustedPublicKey()))
                .isInstanceOf(CoreEventSignature.CoreSignatureException.class);

        // And an envelope whose event type does not belong to the producer claiming it is refused even before
        // the signature is examined: a result signed by case-service is not a result.
        ObjectNode wrongProducer = (ObjectNode) MAPPER.readTree(stored.envelope());
        wrongProducer.put("producer", CoreEnvelope.COMMERCE_SERVICE);
        assertThatThrownBy(() -> CoreEnvelope.verify(wrongProducer, trustedPublicKey()))
                .isInstanceOf(CoreEnvelope.EnvelopeException.class);
    }

    @Test
    @DisplayName("an event and the effect it reports share one commit")
    void anEventIsWrittenInTheDecidingTransaction() {
        RefundCommand command = command();

        // The transaction is opened by the template rather than by a @Transactional test method: a self-invoked
        // method on the test instance never goes through the proxy, so its annotation would do nothing and the
        // test would pass while proving the opposite.
        assertThatThrownBy(() -> transactions.execute(status -> {
                    outbox.writeRefundCommand(
                            command.caseId(), command.authorizationId(), MERCHANT, command, traceparent());
                    throw new IllegalStateException("the business step failed after writing its event");
                }))
                .isInstanceOf(IllegalStateException.class);

        assertThat(jdbc.queryForObject("SELECT COUNT(*) FROM event_outbox", Integer.class))
                .as("the event rolled back with the effect that would have produced it")
                .isZero();
    }

    @Test
    @DisplayName("a delivery pass publishes what is due and marks it published")
    void aDeliveryPassPublishes() {
        String eventId = writeCommand();

        OutboxDeliveryService.Pass pass = delivery.deliverDue(10);

        assertThat(pass.published()).isEqualTo(1);
        assertThat(pass.failed()).isZero();
        assertThat(publisher.published).containsExactly(CoreEnvelope.CASE_TOPIC + ":" + eventId);
        OutboxEvent stored = outboxRepository.find(eventId);
        assertThat(stored.isPublished()).isTrue();
        assertThat(stored.publishedAt()).isNotNull();
        assertThat(stored.attempts()).isEqualTo(1);
    }

    @Test
    @DisplayName("a second pass finds nothing left to publish")
    void publishingIsNotRepeatedByTheLoop() {
        writeCommand();
        delivery.deliverDue(10);

        OutboxDeliveryService.Pass second = delivery.deliverDue(10);

        assertThat(second.published()).isZero();
        assertThat(second.failed()).isZero();
        assertThat(publisher.published).hasSize(1);
    }

    @Test
    @DisplayName("a failed publish keeps the event and schedules another attempt")
    void aFailedPublishIsRetried() {
        String eventId = writeCommand();
        publisher.failuresRemaining = 1;
        publisher.lastError = "broker refused the connection";

        OutboxDeliveryService.Pass pass = delivery.deliverDue(10);

        assertThat(pass.failed()).isEqualTo(1);
        OutboxEvent stored = outboxRepository.find(eventId);
        assertThat(stored.status()).as("a failure is not a loss").isEqualTo("PENDING");
        assertThat(stored.attempts()).isEqualTo(1);
        assertThat(stored.lastError()).contains("broker refused the connection");
        assertThat(stored.nextAttemptAt())
                .as("and there is a next attempt time")
                .isNotNull();

        // The next pass cannot pick it up yet: the backoff is real, not decorative.
        assertThat(delivery.deliverDue(10).published()).isZero();
    }

    @Test
    @DisplayName("attempts exhausted leaves the event as DEAD rather than deleting it")
    void exhaustedAttemptsAreKeptAsDead() {
        OutboxDeliveryService strict = new OutboxDeliveryService(outboxRepository, publisher, Clock.systemUTC(), 2, 1);
        String eventId = writeCommand();
        publisher.failuresRemaining = 10;

        OutboxDeliveryService.Pass first = strict.deliverDue(10);
        assertThat(first.failed()).isEqualTo(1);
        // Clear the backoff so the next pass can try again immediately; the point under test is the attempt
        // limit, not the waiting.
        jdbc.update("UPDATE event_outbox SET next_attempt_at = NULL WHERE event_id = ?", eventId);

        OutboxDeliveryService.Pass second = strict.deliverDue(10);

        assertThat(second.dead()).isEqualTo(1);
        OutboxEvent stored = outboxRepository.find(eventId);
        assertThat(stored.isDead()).isTrue();
        assertThat(stored.attempts()).isEqualTo(2);
        assertThat(stored.lastError()).isNotBlank();
        assertThat(stored.nextAttemptAt())
                .as("a dead event is not scheduled again")
                .isNull();
        assertThat(delivery.deliverDue(10).published())
                .as("and the ordinary loop does not resurrect it")
                .isZero();
    }

    @Test
    @DisplayName("events are published in the order they were written")
    void eventsArePublishedInOrder() throws InterruptedException {
        String first = writeCommand();
        Thread.sleep(5);
        String second = writeCommand();

        delivery.deliverDue(10);

        assertThat(publisher.published)
                .containsExactly(CoreEnvelope.CASE_TOPIC + ":" + first, CoreEnvelope.CASE_TOPIC + ":" + second);
    }

    @Test
    @DisplayName("the command producer cannot originate a result, because only the command entry point exists")
    void aResultCannotBeSignedByTheCommandProducer() {
        // What is asserted is the reachable surface, not a runtime check: case-service exposes a command
        // writer and nothing generic, so a result envelope cannot be built here at all. The rule that decides
        // which service may produce which event lives in CoreEnvelope and is asserted below.
        assertThat(java.util.Arrays.stream(EventOutbox.class.getDeclaredMethods())
                        .filter(method -> java.lang.reflect.Modifier.isPublic(method.getModifiers()))
                        .map(java.lang.reflect.Method::getName))
                .as("a generic 'write any event' helper would let this service sign a message from the other one")
                .doesNotContain("write");

        assertThat(CoreEnvelope.producerOf(CoreEnvelope.REFUND_SUCCEEDED))
                .as("a result belongs to commerce-service, whatever this service would like")
                .isEqualTo(CoreEnvelope.COMMERCE_SERVICE);
        assertThat(CoreEnvelope.producerOf(CoreEnvelope.REFUND_REQUESTED)).isEqualTo(CoreEnvelope.CASE_SERVICE);

        // And an event type outside the core four is refused rather than mapped to somebody.
        assertThatThrownBy(() -> CoreEnvelope.producerOf("ReshipSucceeded"))
                .isInstanceOf(CoreEnvelope.EnvelopeException.class)
                .hasMessageContaining("not a core event type");
        assertThat(outboxRepository.countByStatus("PENDING")).isZero();
    }

    @Test
    @DisplayName("a bad traceparent is refused rather than stored unverifiable")
    void aMalformedTraceparentIsRefused() {
        RefundCommand command = command();

        assertThatThrownBy(() -> outbox.writeRefundCommand(
                        command.caseId(), command.authorizationId(), MERCHANT, command, "not-a-traceparent"))
                .isInstanceOf(CoreEnvelope.EnvelopeException.class);
        assertThat(outboxRepository.countByStatus("PENDING")).isZero();
    }

    @Test
    @DisplayName("the stored envelope can be read back as a tree, which is what the transport publishes")
    void theStoredEnvelopeIsReadable() {
        String eventId = writeCommand();

        ObjectNode envelope = outbox.envelopeOf(eventId);

        assertThat(envelope.get("event_id").stringValue()).isEqualTo(eventId);
        assertThat(CoreEnvelope.canonical(envelope))
                .isEqualTo(outboxRepository.find(eventId).envelope());
    }

    @Test
    @DisplayName("the backoff grows with each attempt and does not overflow")
    void theBackoffGrows() {
        OutboxDeliveryService service =
                new OutboxDeliveryService(outboxRepository, publisher, Clock.systemUTC(), 20, 5);

        assertThat(service.backoffFor(1)).isEqualTo(Duration.ofSeconds(5));
        assertThat(service.backoffFor(2)).isEqualTo(Duration.ofSeconds(10));
        assertThat(service.backoffFor(3)).isEqualTo(Duration.ofSeconds(20));
        assertThat(service.backoffFor(40))
                .as("a long outage must not overflow into a negative wait")
                .isEqualTo(Duration.ofSeconds(5).multipliedBy(1024));
    }

    @Test
    @DisplayName("a command id is unique per authorisation and per operation, enforced by the schema")
    void oneAuthorisationSendsOneCommand() {
        RefundCommand command = command();
        String eventId = outbox.writeRefundCommand(
                command.caseId(), command.authorizationId(), MERCHANT, command, traceparent());
        // A JDBC parameter, not an Instant: the driver maps java.time through its own conversions and the
        // timestamp column wants a Timestamp.
        java.sql.Timestamp now = java.sql.Timestamp.from(Instant.now());

        assertThatThrownBy(() -> jdbc.update(
                        "INSERT INTO case_execution_command (authorization_id, case_id, operation_id, event_id,"
                                + " input_revision, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                        command.authorizationId(),
                        command.caseId(),
                        UUID.randomUUID().toString(),
                        eventId,
                        2,
                        now))
                .as("a second command for one authorisation is refused by the primary key")
                .isInstanceOf(org.springframework.dao.DataIntegrityViolationException.class);
    }
}
