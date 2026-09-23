package com.resolveflow.commerce.messaging;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

import com.resolveflow.commerce.CommerceDatabaseTest;
import com.resolveflow.commerce.refund.RefundAcceptanceService;
import com.resolveflow.shared.contract.CanonicalJson;
import com.resolveflow.shared.core.CoreEnvelope;
import java.security.PrivateKey;
import java.time.Instant;
import java.util.UUID;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.jdbc.core.JdbcTemplate;
import tools.jackson.databind.ObjectMapper;
import tools.jackson.databind.node.ObjectNode;

/**
 * Consuming a signed refund command over an at-least-once transport (C05.1b, docs/domain-model.md:45,47).
 *
 * <p>The properties under test are the ones that make a message broker safe to use for money:
 *
 * <ul>
 *   <li><b>A redelivery is harmless.</b> The inbox claims the event id, so the second delivery reserves
 *       nothing — and the transport is allowed to deliver twice, which it will.
 *   <li><b>Only a trusted producer is obeyed.</b> A valid signature from an unknown key is refused: the
 *       signature proves integrity, and the trust list proves origin.
 *   <li><b>A refusal is kept even though the consumer failed.</b> The rejection is written in its own
 *       transaction, so it survives the consumer's rollback — otherwise the one row an operator needs is the
 *       one that disappeared.
 *   <li><b>The command is applied through C04.2's path, not re-implemented.</b> The money facts asserted here
 *       (reservation, slot, ledger) are the same ones, because it is the same code.
 * </ul>
 */
class RefundCommandConsumerApiTest extends CommerceDatabaseTest {

    private static final ObjectMapper MAPPER = new ObjectMapper();
    private static final String MERCHANT = "M-1001";
    private static final String LINE_7001 = "7001";
    private static final String TRACEPARENT = "00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01";

    /** The fixture key pair: the same one case-service signs with locally, so this test exercises the
     *  producer/consumer agreement rather than a test-only shortcut. */
    private static PrivateKey producerKey() {
        return CoreEnvelope.privateKeyFromPkcs8Base64(com.resolveflow.shared.core.CoreFixtures.privateKeyPkcs8Base64());
    }

    @Autowired
    RefundCommandConsumer consumer;

    @Autowired
    EventInboxRepository inbox;

    @Autowired
    RefundAcceptanceService acceptance;

    @Autowired
    JdbcTemplate jdbc;

    @BeforeEach
    void reset() {
        jdbc.execute("DELETE FROM event_rejection");
        jdbc.execute("DELETE FROM event_inbox");
        jdbc.execute("DELETE FROM refund_request_inbox");
        jdbc.execute("DELETE FROM refund_operation");
        jdbc.execute("UPDATE line_refund SET state = 'FREE', operation_id = NULL, version = 1");
        jdbc.execute("UPDATE payment_ledger SET refunded_amount = 0, reserved_refund_amount = 0, version = 1");
    }

    // ------------------------------------------------------------------ fixtures

    private ObjectNode commandPayload(String operationId, long amountMinor) {
        ObjectNode payload = MAPPER.createObjectNode();
        payload.put("operation_id", operationId);
        payload.put("case_id", UUID.randomUUID().toString());
        payload.put("authorization_id", UUID.randomUUID().toString());
        payload.put("input_revision", 2);
        payload.put("line_id", LINE_7001);
        payload.put("merchant_id", MERCHANT);
        payload.put("action", "REFUND");
        payload.put("quantity", 2);
        payload.put("currency", "CNY");
        payload.put("amount_minor", amountMinor);
        payload.put("policy_version", "2026.09");
        payload.put("target_service", "commerce-service");
        payload.put("payload_hash", CanonicalJson.payloadHash(payload));
        return payload;
    }

    /** The command as it travels: signed by case-service's key, with the authorisation as its cause. */
    private String signedCommand(String operationId, long amountMinor) {
        ObjectNode payload = commandPayload(operationId, amountMinor);
        ObjectNode envelope = CoreEnvelope.sign(
                UUID.randomUUID().toString(),
                CoreEnvelope.REFUND_REQUESTED,
                MERCHANT,
                Instant.now(),
                payload,
                payload.get("authorization_id").stringValue(),
                TRACEPARENT,
                "case-service-demo-key",
                producerKey());
        return CoreEnvelope.canonical(envelope);
    }

    private long reserved() {
        return jdbc.queryForObject(
                "SELECT reserved_refund_amount FROM payment_ledger WHERE order_id = ?",
                Long.class,
                jdbc.queryForObject("SELECT order_id FROM order_line WHERE line_id = ?", String.class, LINE_7001));
    }

    private String slotState() {
        return jdbc.queryForObject("SELECT state FROM line_refund WHERE line_id = ?", String.class, LINE_7001);
    }

    // ------------------------------------------------------------------ the cases

    @Test
    @DisplayName("a signed command reserves the money through the same path C04.2 owns")
    void aSignedCommandReservesTheMoney() {
        String operationId = UUID.randomUUID().toString();

        RefundCommandConsumer.Disposition disposition = consumer.consume(signedCommand(operationId, 2599));

        assertThat(disposition).isEqualTo(RefundCommandConsumer.Disposition.ACCEPTED);
        assertThat(reserved()).isEqualTo(2599);
        assertThat(slotState()).isEqualTo("RESERVED");
        assertThat(jdbc.queryForObject(
                        "SELECT COUNT(*) FROM refund_operation WHERE operation_id = ?", Integer.class, operationId))
                .isEqualTo(1);
        assertThat(jdbc.queryForObject("SELECT COUNT(*) FROM event_inbox", Integer.class))
                .isEqualTo(1);
    }

    @Test
    @DisplayName("a redelivered command reserves nothing the second time")
    void aRedeliveredCommandIsHarmless() {
        String operationId = UUID.randomUUID().toString();
        String message = signedCommand(operationId, 2599);

        assertThat(consumer.consume(message)).isEqualTo(RefundCommandConsumer.Disposition.ACCEPTED);
        assertThat(consumer.consume(message))
                .as("the transport is allowed to deliver twice; the money is not")
                .isEqualTo(RefundCommandConsumer.Disposition.DUPLICATE);

        assertThat(reserved()).isEqualTo(2599);
        assertThat(jdbc.queryForObject("SELECT COUNT(*) FROM refund_operation", Integer.class))
                .isEqualTo(1);
        assertThat(jdbc.queryForObject("SELECT COUNT(*) FROM event_inbox", Integer.class))
                .isEqualTo(1);
    }

    @Test
    @DisplayName("a command signed by an untrusted key is refused and recorded")
    void anUntrustedKeyIsRefused() {
        ObjectNode payload = commandPayload(UUID.randomUUID().toString(), 2599);
        ObjectNode envelope = CoreEnvelope.sign(
                UUID.randomUUID().toString(),
                CoreEnvelope.REFUND_REQUESTED,
                MERCHANT,
                Instant.now(),
                payload,
                null,
                null,
                // A key this service has never heard of, with a genuine signature over the document.
                "some-other-key",
                producerKey());

        assertThatThrownBy(() -> consumer.consume(CoreEnvelope.canonical(envelope)))
                .isInstanceOf(EventVerifier.RefusedEventException.class)
                .satisfies(error -> assertThat(((EventVerifier.RefusedEventException) error).refusal())
                        .isEqualTo(EventVerifier.Refusal.UNTRUSTED_KEY));
        assertThat(reserved())
                .as("a message from an unknown signer moves no money")
                .isZero();
        assertThat(inbox.rejections()).hasSize(1);
        assertThat(inbox.rejections().get(0).reason()).isEqualTo("UNTRUSTED_KEY");
        assertThat(inbox.find(
                        EventTrustConfiguration.REFUND_COMMAND_CONSUMER,
                        envelope.get("event_id").stringValue()))
                .as("a refused event is not in the inbox: it was never applied")
                .isNull();
    }

    @Test
    @DisplayName("a tampered envelope fails verification even with a trusted key id")
    void aTamperedEnvelopeIsRefused() {
        ObjectNode payload = commandPayload(UUID.randomUUID().toString(), 2599);
        String message = CoreEnvelope.canonical(CoreEnvelope.sign(
                UUID.randomUUID().toString(),
                CoreEnvelope.REFUND_REQUESTED,
                MERCHANT,
                Instant.now(),
                payload,
                null,
                null,
                "case-service-demo-key",
                producerKey()));

        // The amount is changed after signing: the signature still carries the trusted key id, and the
        // payload_hash inside the document no longer matches either. Both are caught, and the signature is
        // the first line of defence.
        String tampered = message.replace("2599", "1");
        assertThat(tampered)
                .as("the tamper has to actually change the document")
                .isNotEqualTo(message);

        assertThatThrownBy(() -> consumer.consume(tampered))
                .isInstanceOf(EventVerifier.RefusedEventException.class)
                .satisfies(error -> assertThat(((EventVerifier.RefusedEventException) error).refusal())
                        .isEqualTo(EventVerifier.Refusal.BAD_SIGNATURE));
        assertThat(reserved()).isZero();
        assertThat(inbox.rejections()).hasSize(1);
    }

    @Test
    @DisplayName("a result event sent to the command consumer is refused as the wrong direction")
    void aResultIsNotACommand() {
        ObjectNode payload = CoreEnvelope.resultPayload(
                UUID.randomUUID().toString(), LINE_7001, CoreEnvelope.SUCCEEDED, 2599, "prv-1", null, 3);
        // Properly signed, and its own envelope is internally consistent (a result comes from commerce-service).
        // What makes it wrong here is the subscription: this consumer executes commands, so a result arriving
        // on the command topic is a routing mistake, and applying it would reserve money nothing asked for.
        String message = CoreEnvelope.canonical(CoreEnvelope.sign(
                UUID.randomUUID().toString(),
                CoreEnvelope.REFUND_SUCCEEDED,
                MERCHANT,
                Instant.now(),
                payload,
                null,
                null,
                "case-service-demo-key",
                producerKey()));

        assertThatThrownBy(() -> consumer.consume(message))
                .isInstanceOf(EventVerifier.RefusedEventException.class)
                .satisfies(error -> assertThat(((EventVerifier.RefusedEventException) error).refusal())
                        .isEqualTo(EventVerifier.Refusal.WRONG_DIRECTION));
        assertThat(inbox.rejections()).hasSize(1);
        assertThat(reserved()).isZero();
    }

    @Test
    @DisplayName("a message that is not an envelope is refused and kept for an operator")
    void garbageIsRefusedAndKept() {
        assertThatThrownBy(() -> consumer.consume("this is not a core event"))
                .isInstanceOf(EventVerifier.RefusedEventException.class)
                .satisfies(error -> assertThat(((EventVerifier.RefusedEventException) error).refusal())
                        .isEqualTo(EventVerifier.Refusal.MALFORMED));

        assertThat(inbox.rejections()).hasSize(1);
        assertThat(inbox.rejections().get(0).reason()).isEqualTo("MALFORMED");
        assertThat(reserved()).isZero();
    }

    @Test
    @DisplayName("a command the world refuses rolls back, so the transport may retry it")
    void aRefusedCommandRollsBack() {
        // The line does not exist in commerce, so the acceptance path refuses. That is a *business* refusal, not
        // a message the consumer should hide from the transport: if the line is added, the same delivery becomes
        // applicable, so the claim has to roll back with the failure.
        ObjectNode payload = commandPayloadFor(
                UUID.randomUUID().toString(), 2599, UUID.randomUUID().toString());
        payload.put("line_id", "9999");
        payload.put("payload_hash", CanonicalJson.payloadHash(withoutHash(payload)));
        String eventId = UUID.randomUUID().toString();
        String message = CoreEnvelope.canonical(CoreEnvelope.sign(
                eventId,
                CoreEnvelope.REFUND_REQUESTED,
                MERCHANT,
                Instant.now(),
                payload,
                null,
                null,
                "case-service-demo-key",
                producerKey()));

        assertThatThrownBy(() -> consumer.consume(message))
                .isInstanceOf(com.resolveflow.commerce.refund.RefundRejectedException.class);

        assertThat(jdbc.queryForObject("SELECT COUNT(*) FROM refund_operation", Integer.class))
                .as("the failed command reserved nothing")
                .isZero();
        assertThat(inbox.find(EventTrustConfiguration.REFUND_COMMAND_CONSUMER, eventId))
                .as("its inbox claim rolled back, so the transport may retry it after the bug is fixed")
                .isNull();
        assertThat(inbox.rejections())
                .as("a business refusal is not a protocol rejection, so nothing is filed as poison")
                .isEmpty();
    }

    @Test
    @DisplayName("a protocol refusal is filed even though the consumer's transaction fails")
    void aProtocolRefusalSurvivesTheFailedTransaction() {
        // This is the case the separate rejection transaction exists for: the consumer is about to fail, and a
        // row written inside its transaction would disappear with it — leaving an operator with a log line and
        // no record of what arrived.
        ObjectNode payload = commandPayload(UUID.randomUUID().toString(), 2599);
        String eventId = UUID.randomUUID().toString();
        String message = CoreEnvelope.canonical(CoreEnvelope.sign(
                eventId,
                CoreEnvelope.REFUND_REQUESTED,
                MERCHANT,
                Instant.now(),
                payload,
                null,
                null,
                "an-untrusted-key",
                producerKey()));

        assertThatThrownBy(() -> consumer.consume(message)).isInstanceOf(EventVerifier.RefusedEventException.class);

        assertThat(inbox.rejections())
                .as("the refusal outlived the consumer's rollback")
                .hasSize(1);
        assertThat(inbox.rejections().get(0).eventId())
                .as("and it names the event, so the message can be found again")
                .isEqualTo(eventId);
        assertThat(inbox.rejections().get(0).reason()).isEqualTo("UNTRUSTED_KEY");
    }

    @Test
    @DisplayName("the same event id with different money is a duplicate, not a second reservation")
    void theSameEventIdIsNotASecondReservation() {
        String operationId = UUID.randomUUID().toString();
        ObjectNode first = commandPayloadFor(operationId, 2599, "auth-1");
        String eventId = UUID.randomUUID().toString();
        String message = CoreEnvelope.canonical(CoreEnvelope.sign(
                eventId,
                CoreEnvelope.REFUND_REQUESTED,
                MERCHANT,
                Instant.now(),
                first,
                null,
                null,
                "case-service-demo-key",
                producerKey()));
        assertThat(consumer.consume(message)).isEqualTo(RefundCommandConsumer.Disposition.ACCEPTED);

        // A second message reusing the *event id* but carrying different money: the inbox refuses it as a
        // duplicate, so the changed amount never reaches the acceptance path.
        ObjectNode second = commandPayloadFor(UUID.randomUUID().toString(), 100, "auth-2");
        String changed = CoreEnvelope.canonical(CoreEnvelope.sign(
                eventId,
                CoreEnvelope.REFUND_REQUESTED,
                MERCHANT,
                Instant.now(),
                second,
                null,
                null,
                "case-service-demo-key",
                producerKey()));

        assertThat(consumer.consume(changed)).isEqualTo(RefundCommandConsumer.Disposition.DUPLICATE);
        assertThat(reserved()).isEqualTo(2599);
        assertThat(jdbc.queryForObject("SELECT COUNT(*) FROM refund_operation", Integer.class))
                .isEqualTo(1);
    }

    private ObjectNode commandPayloadFor(String operationId, long amountMinor, String authorizationId) {
        ObjectNode payload = commandPayload(operationId, amountMinor);
        payload.put("authorization_id", authorizationId);
        payload.put("payload_hash", CanonicalJson.payloadHash(withoutHash(payload)));
        return payload;
    }

    private static ObjectNode withoutHash(ObjectNode payload) {
        ObjectNode copy = payload.deepCopy();
        copy.remove("payload_hash");
        return copy;
    }
}
