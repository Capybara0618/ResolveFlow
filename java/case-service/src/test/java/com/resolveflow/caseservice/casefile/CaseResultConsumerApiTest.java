package com.resolveflow.caseservice.casefile;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

import com.resolveflow.caseservice.CaseDatabaseTest;
import com.resolveflow.caseservice.policy.PolicyImportService;
import com.resolveflow.caseservice.policy.PolicyRule;
import com.resolveflow.caseservice.result.CaseResultConsumer;
import com.resolveflow.caseservice.result.CaseResultInboxRepository;
import com.resolveflow.caseservice.result.CaseResultTrustConfiguration;
import com.resolveflow.caseservice.result.CaseResultVerifier;
import com.resolveflow.shared.core.CoreEnvelope;
import com.resolveflow.shared.security.AuthenticatedPrincipal;
import com.resolveflow.shared.security.JwtCodec;
import com.resolveflow.shared.security.Role;
import java.security.PrivateKey;
import java.time.Duration;
import java.time.Instant;
import java.util.UUID;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.boot.resttestclient.autoconfigure.AutoConfigureRestTestClient;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.boot.test.context.TestConfiguration;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Primary;
import org.springframework.http.MediaType;
import org.springframework.test.web.servlet.client.RestTestClient;
import tools.jackson.databind.ObjectMapper;
import tools.jackson.databind.node.ObjectNode;

/**
 * Consuming a signed refund result over an at-least-once transport (C05.2b-3a, docs/core-contracts.md:86).
 *
 * <p>Case-service is now the <em>consumer</em>: Commerce signs its results (C05.2b-1) and this service has to
 * decide whether to believe them before anything is written down. The properties under test are the mirror of
 * C05.1b's, and for the same reasons:
 *
 * <ul>
 *   <li><b>Only a trusted, genuine result is obeyed.</b> The signature proves integrity, the trust map proves
 *       origin, and a tampered payload proves nothing but that the signature is doing its job.
 *   <li><b>A redelivery is harmless.</b> At-least-once means the transport <em>will</em> deliver twice; the
 *       claim is the inbox row, so the second delivery stores nothing a second time.
 *   <li><b>The result is scoped to the case it belongs to.</b> A result for another merchant, or for an
 *       operation this service never issued, is refused loudly rather than filed against the nearest case.
 *   <li><b>Receiving a result is not projecting it.</b> The last test is the boundary of this sub-step: after a
 *       {@code RefundSucceeded} is accepted and stored, the case is still {@code EXECUTING}. Moving it belongs
 *       to C05.2b-3b, and pretending otherwise would be the one thing this test must not do.
 * </ul>
 *
 * <p>The class lives in the casefile package because that is where the other case-API tests and their
 * package-private {@link StubCommerce} live; the classes under test are the ones in the result package.
 */
@SpringBootTest(webEnvironment = SpringBootTest.WebEnvironment.RANDOM_PORT)
@AutoConfigureRestTestClient
class CaseResultConsumerApiTest extends CaseDatabaseTest {

    private static final ObjectMapper MAPPER = new ObjectMapper();
    private static final String MERCHANT = "M-1001";
    private static final String CUSTOMER = "C-2002";
    private static final String RUN = "b3a0b3a0-5555-4666-8777-b3a0b3a0b3a0";
    private static final String BUNDLE = "policy-logistics-2026.09";
    private static final String VERSION = "2026.09";
    private static final String TRACEPARENT = "00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01";

    /** The result producer's key: Commerce signs with the same corpus fixture key pair (per-service key ids). */
    private static PrivateKey producerKey() {
        return CoreEnvelope.privateKeyFromPkcs8Base64(com.resolveflow.shared.core.CoreFixtures.privateKeyPkcs8Base64());
    }

    @TestConfiguration
    static class StubCommerceConfiguration {

        @Bean
        @Primary
        StubCommerce commerceStub(
                org.springframework.web.client.RestClient.Builder builder,
                @Value("${resolveflow.identity.jwt.secret}") String secret,
                @Value("${resolveflow.identity.jwt.service-token-ttl:PT1H}") Duration ttl) {
            return new StubCommerce(builder, new JwtCodec(secret, ttl));
        }
    }

    @Autowired
    CaseResultConsumer consumer;

    @Autowired
    CaseResultInboxRepository inbox;

    @Autowired
    AuthorizationConsumptionService consumption;

    @Autowired
    AuthorizationRepository authorizations;

    @Autowired
    PolicyImportService policies;

    @Autowired
    StubCommerce commerce;

    @Autowired
    RestTestClient rest;

    @Value("${resolveflow.identity.jwt.secret}")
    String secret;

    /** The case every test delivers to: opened, proposed, approved and dispatched, so it is EXECUTING. */
    private String caseId;

    private String operationId;

    private long lineCounter = 8100;

    @BeforeEach
    void prepare() {
        // The inbox and its rejection log are cleaned by deleteAllCaseData, which owns the foreign-key order for
        // the whole suite (C05.2b-3a added them there); naming them again here would be a second copy of it.
        deleteAllCaseData(jdbc);
        commerce.reset();
        installPolicies();

        caseId = executingCase();
        operationId = jdbc.queryForObject(
                "SELECT operation_id FROM case_execution_command WHERE case_id = ?", String.class, caseId);
        assertThat(caseStatus())
                .as("the fixture has to reach EXECUTING before a result can be delivered")
                .isEqualTo("EXECUTING");
    }

    private void installPolicies() {
        jdbc.execute("DELETE FROM case_policy_bundle");
        jdbc.execute("DELETE FROM case_policy_manifest");
        jdbc.execute("DELETE FROM policy_rule");
        jdbc.execute("DELETE FROM policy_bundle");
        policies.importDirectory(fixtureDirectory());
    }

    private static java.nio.file.Path fixtureDirectory() {
        java.nio.file.Path candidate = java.nio.file.Path.of("").toAbsolutePath();
        for (int level = 0; level < 5 && candidate != null; level++) {
            java.nio.file.Path bundles =
                    candidate.resolve("fixtures").resolve("policies").resolve("bundles");
            if (java.nio.file.Files.isDirectory(bundles)) {
                return bundles;
            }
            candidate = candidate.getParent();
        }
        throw new IllegalStateException("fixtures/policies/bundles not found");
    }

    // ------------------------------------------------------------------ the cases

    @Test
    @DisplayName("a signed RefundSucceeded result is verified and stored against the case it belongs to")
    void aSignedResultIsStoredAgainstItsCase() {
        String eventId = UUID.randomUUID().toString();

        CaseResultConsumer.Disposition disposition = consumer.consume(succeeded(eventId, MERCHANT, 3));

        assertThat(disposition).isEqualTo(CaseResultConsumer.Disposition.ACCEPTED);
        CaseResultInboxRepository.StoredResult stored =
                inbox.find(CaseResultTrustConfiguration.RESULT_CONSUMER, eventId);
        assertThat(stored).as("the fact is durable, not just a return value").isNotNull();
        assertThat(stored.caseId()).isEqualTo(caseId);
        assertThat(stored.operationId()).isEqualTo(operationId);
        assertThat(stored.state()).isEqualTo(CoreEnvelope.SUCCEEDED);
        assertThat(stored.amountMinor()).isEqualTo(2599);
        assertThat(stored.aggregateVersion()).isEqualTo(3);
        assertThat(stored.providerRef()).isEqualTo("prv-b3a-1");
        assertThat(stored.reasonCode()).isNull();
        assertThat(stored.signingKeyId()).isEqualTo("commerce-service-demo-key");
        assertThat(stored.envelope())
                .as("the verified document is kept — canonically serialised, not byte-verbatim: key order and"
                        + " whitespace are normalised — which is what makes the verification reproducible")
                .contains(eventId);
        assertThat(stored.signature()).isNotBlank();
        assertThat(stored.projectedAt())
                .as("C05.2b-3b slice ① applies a SUCCEEDED result inside this same transaction, so the row says so")
                .isNotNull();
    }

    @Test
    @DisplayName("a result whose payload was changed after signing is refused and stores nothing")
    void aTamperedResultIsRefused() {
        String eventId = UUID.randomUUID().toString();
        String message = succeeded(eventId, MERCHANT, 3);

        String tampered = message.replace("2599", "1");
        assertThat(tampered)
                .as("the tamper has to actually change the document")
                .isNotEqualTo(message);

        assertThatThrownBy(() -> consumer.consume(tampered))
                .isInstanceOf(CaseResultVerifier.RefusedEventException.class)
                .satisfies(error -> assertThat(((CaseResultVerifier.RefusedEventException) error).refusal())
                        .isEqualTo(CaseResultVerifier.Refusal.BAD_SIGNATURE));

        assertThat(inbox.find(CaseResultTrustConfiguration.RESULT_CONSUMER, eventId))
                .as("a result that failed verification is not a fact")
                .isNull();
        assertThat(inbox.rejections()).hasSize(1);
        assertThat(inbox.rejections().get(0).reason()).isEqualTo("BAD_SIGNATURE");
    }

    @Test
    @DisplayName("a result whose amount is outside the core range is refused and recorded, not retried forever")
    void anAmountOutsideTheCoreRangeIsRefused() {
        // C05.3a's second finding, closed here. The amount was only checked as "a number", so 0 — or anything
        // above the contract's maximum of 1000000000 — travelled to the table's own CHECK constraint and came
        // back as DataIntegrityViolationException. That is not a refusal: the transaction rolled back, nothing
        // was written down, and the transport redelivered a message that could never be accepted. An operator
        // had no row to find, which is the one outcome this consumer exists to prevent.
        String belowMinimum = UUID.randomUUID().toString();
        String aboveMaximum = UUID.randomUUID().toString();

        assertThatThrownBy(() -> consumer.consume(resultEnvelope(
                        belowMinimum,
                        MERCHANT,
                        CoreEnvelope.SUCCEEDED,
                        0,
                        "prv-range-test",
                        null,
                        3,
                        "commerce-service-demo-key",
                        producerKey())))
                .as("0 is below the contract's minimum of 1")
                .isInstanceOf(CaseResultVerifier.RefusedEventException.class)
                .satisfies(error -> assertThat(((CaseResultVerifier.RefusedEventException) error).refusal())
                        .isEqualTo(CaseResultVerifier.Refusal.MALFORMED));
        assertThatThrownBy(() -> consumer.consume(resultEnvelope(
                        aboveMaximum,
                        MERCHANT,
                        CoreEnvelope.SUCCEEDED,
                        1_000_000_001L,
                        "prv-range-test",
                        null,
                        3,
                        "commerce-service-demo-key",
                        producerKey())))
                .as("and 1000000001 is above its maximum")
                .isInstanceOf(CaseResultVerifier.RefusedEventException.class);

        assertThat(inbox.find(CaseResultTrustConfiguration.RESULT_CONSUMER, belowMinimum))
                .as("a result this service cannot read is not a fact")
                .isNull();
        assertThat(inbox.rejections())
                .as("both ends of the range are recorded, so the broken producer is visible")
                .hasSize(2);
        assertThat(inbox.rejections().get(0).reason()).isEqualTo("MALFORMED");
    }

    @Test
    @DisplayName("a result whose state this version does not know is refused and recorded")
    void anUnknownStateIsRefusedAndRecorded() {
        // C05.3a's first finding: fixed in code then, never pinned by a test — the fixture helper derives the
        // event type *from* the state (and CoreEnvelope.resultPayload refuses a state outside the contract), so
        // no test could produce the document this path exists for. A trusted producer can still send one: a
        // newer Commerce, or a bug. The shared helper's exception used to escape the refusal conversion, which
        // rolled the transaction back without a rejection row and redelivered forever. This is that document,
        // built by hand and signed properly, because "correctly signed" is not the same as "readable".
        String eventId = UUID.randomUUID().toString();

        assertThatThrownBy(() -> consumer.consume(aCorrectlySignedResultWithState(eventId, "CREATED", 2599, 3)))
                .as("CREATED is a Commerce-local state, not a core result state")
                .isInstanceOf(CaseResultVerifier.RefusedEventException.class)
                .satisfies(error -> assertThat(((CaseResultVerifier.RefusedEventException) error).refusal())
                        .isEqualTo(CaseResultVerifier.Refusal.MALFORMED));

        assertThat(inbox.find(CaseResultTrustConfiguration.RESULT_CONSUMER, eventId))
                .as("a result nobody can interpret is not a fact")
                .isNull();
        assertThat(inbox.rejections())
                .as("and it is filed, so a state this version cannot read is visible rather than invisible")
                .hasSize(1);
        assertThat(inbox.rejections().get(0).reason()).isEqualTo("MALFORMED");
    }

    @Test
    @DisplayName("a result signed with a key this service does not trust is refused")
    void anUntrustedSigningKeyIsRefused() {
        String eventId = UUID.randomUUID().toString();
        // A genuine signature over a genuine document, made with a key id this service has never heard of.
        String message = resultEnvelope(
                eventId, MERCHANT, CoreEnvelope.SUCCEEDED, 2599, "prv-b3a-1", null, 3, "some-other-key", producerKey());

        assertThatThrownBy(() -> consumer.consume(message))
                .isInstanceOf(CaseResultVerifier.RefusedEventException.class)
                .satisfies(error -> assertThat(((CaseResultVerifier.RefusedEventException) error).refusal())
                        .isEqualTo(CaseResultVerifier.Refusal.UNTRUSTED_KEY));

        assertThat(inbox.find(CaseResultTrustConfiguration.RESULT_CONSUMER, eventId))
                .isNull();
        assertThat(inbox.rejections()).hasSize(1);
        assertThat(inbox.rejections().get(0).reason()).isEqualTo("UNTRUSTED_KEY");
    }

    @Test
    @DisplayName("a result for another merchant is refused loudly and stores nothing")
    void aResultForAnotherMerchantIsRefused() {
        String eventId = UUID.randomUUID().toString();

        assertThatThrownBy(() -> consumer.consume(succeeded(eventId, "M-1002", 3)))
                .isInstanceOf(CaseResultVerifier.RefusedEventException.class)
                .satisfies(error -> assertThat(((CaseResultVerifier.RefusedEventException) error).refusal())
                        .isEqualTo(CaseResultVerifier.Refusal.WRONG_MERCHANT));

        assertThat(inbox.find(CaseResultTrustConfiguration.RESULT_CONSUMER, eventId))
                .isNull();
        assertThat(inbox.rejections()).hasSize(1);
        assertThat(inbox.rejections().get(0).reason()).isEqualTo("WRONG_MERCHANT");
        assertThat(caseStatus()).isEqualTo("EXECUTING");
    }

    @Test
    @DisplayName("the same result delivered twice stores exactly one row and reports the second as duplicate")
    void aRedeliveredResultStoresOneRow() {
        String eventId = UUID.randomUUID().toString();
        String message = succeeded(eventId, MERCHANT, 3);

        assertThat(consumer.consume(message)).isEqualTo(CaseResultConsumer.Disposition.ACCEPTED);
        assertThat(consumer.consume(message))
                .as("the transport is allowed to deliver twice; the inbox is what makes that harmless")
                .isEqualTo(CaseResultConsumer.Disposition.DUPLICATE);

        assertThat(jdbc.queryForObject(
                        "SELECT COUNT(*) FROM case_result_inbox WHERE case_id = ?", Integer.class, caseId))
                .isEqualTo(1);
        assertThat(inbox.find(CaseResultTrustConfiguration.RESULT_CONSUMER, eventId)
                        .detail())
                .contains("duplicate");
        assertThat(inbox.rejections()).as("a duplicate is not an error").isEmpty();
    }

    @Test
    @DisplayName("a third delivery of the same result is still a duplicate, not a fresh claim")
    void aThirdDeliveryIsStillADuplicate() {
        String eventId = UUID.randomUUID().toString();
        String message = succeeded(eventId, MERCHANT, 3);

        assertThat(consumer.consume(message)).isEqualTo(CaseResultConsumer.Disposition.ACCEPTED);
        assertThat(consumer.consume(message)).isEqualTo(CaseResultConsumer.Disposition.DUPLICATE);
        // The claim statement's affected-row count is what answers this, and it can only tell "claimed" from
        // "already claimed" while the duplicate branch actually changes the row. The *first* redelivery changes
        // `detail` from NULL to the sentence; a later one changes nothing unless the statement keeps writing
        // something new, and MySQL then reports 0 (or 1 under CLIENT_FOUND_ROWS) — never the 2 the caller reads
        // as "duplicate". At-least-once makes a third delivery exactly as normal as a second.
        assertThat(consumer.consume(message))
                .as("a third delivery must not be mistaken for a fresh claim")
                .isEqualTo(CaseResultConsumer.Disposition.DUPLICATE);

        assertThat(jdbc.queryForObject(
                        "SELECT COUNT(*) FROM case_result_inbox WHERE case_id = ?", Integer.class, caseId))
                .isEqualTo(1);
        assertThat(inbox.find(CaseResultTrustConfiguration.RESULT_CONSUMER, eventId)
                        .deliveries())
                .as("every redelivery is counted, which is what makes the affected-row answer deterministic (V14)")
                .isEqualTo(3);
    }

    @Test
    @DisplayName("C05.2b-3b: the boundary b-3a left behind is crossed — a redelivery closes nothing twice")
    void aRedeliveredResultDoesNotCloseTheCaseTwice() {
        String eventId = UUID.randomUUID().toString();
        String message = succeeded(eventId, MERCHANT, 3);

        assertThat(consumer.consume(message)).isEqualTo(CaseResultConsumer.Disposition.ACCEPTED);
        long versionAfterFirst =
                jdbc.queryForObject("SELECT version FROM aftersale_case WHERE case_id = ?", Long.class, caseId);

        // This test used to assert the opposite ("the result is received and *not* projected, because projection
        // is C05.2b-3b's step"). This is that step, so the assertion is rewritten into the fact b-3a promised to
        // hand over rather than deleted: the second delivery finds the claim in the inbox and changes nothing —
        // no second closure, no second timeline row, no second version bump.
        assertThat(consumer.consume(message)).isEqualTo(CaseResultConsumer.Disposition.DUPLICATE);
        assertThat(caseStatus()).isEqualTo("CLOSED_SUCCESS");
        assertThat(jdbc.queryForObject("SELECT version FROM aftersale_case WHERE case_id = ?", Long.class, caseId))
                .as("a duplicate is not a new fact and must not move the case again")
                .isEqualTo(versionAfterFirst);
        assertThat(jdbc.queryForObject(
                        "SELECT COUNT(*) FROM case_timeline WHERE case_id = ? AND kind = 'CASE_CLOSED'",
                        Integer.class,
                        caseId))
                .as("the timeline records what happened, not how often it was delivered")
                .isEqualTo(1);
    }

    @Test
    @DisplayName("a result for an operation this service never issued is refused as unfileable")
    void aResultForAnUnknownOperationIsRefused() {
        String eventId = UUID.randomUUID().toString();
        // Correctly signed and correctly scoped to the merchant — but the operation is one this service has no
        // command for, so there is no case it could be about. Guessing one would file a real result against the
        // wrong case, which is why the refusal is loud.
        String message = resultEnvelope(
                eventId,
                MERCHANT,
                CoreEnvelope.SUCCEEDED,
                2599,
                "prv-b3a-1",
                null,
                3,
                "commerce-service-demo-key",
                producerKey(),
                UUID.randomUUID().toString());

        assertThatThrownBy(() -> consumer.consume(message))
                .isInstanceOf(CaseResultVerifier.RefusedEventException.class)
                .satisfies(error -> assertThat(((CaseResultVerifier.RefusedEventException) error).refusal())
                        .isEqualTo(CaseResultVerifier.Refusal.UNKNOWN_OPERATION));

        assertThat(inbox.find(CaseResultTrustConfiguration.RESULT_CONSUMER, eventId))
                .isNull();
        assertThat(inbox.rejections()).hasSize(1);
        assertThat(inbox.rejections().get(0).reason()).isEqualTo("UNKNOWN_OPERATION");
        assertThat(inbox.rejections().get(0).eventId())
                .as("the rejection names the event, so the message can be found again")
                .isEqualTo(eventId);
    }

    @Test
    @DisplayName("C05.2b-3b: an accepted RefundSucceeded closes the case and records it in the timeline")
    void anAcceptedSuccessClosesTheCase() {
        String eventId = UUID.randomUUID().toString();

        assertThat(consumer.consume(succeeded(eventId, MERCHANT, 3)))
                .isEqualTo(CaseResultConsumer.Disposition.ACCEPTED);

        // docs/core-contracts.md:86 puts the inbox row, the projection and the local timeline in one
        // transaction, so this is the same consume() call and not a later loop: the result that was accepted
        // above is the result that closed the case.
        assertThat(caseStatus())
                .as("the money moved and the case heard about it")
                .isEqualTo("CLOSED_SUCCESS");
        assertThat(jdbc.queryForObject(
                        "SELECT COUNT(*) FROM case_timeline WHERE case_id = ? AND kind = 'CASE_CLOSED'",
                        Integer.class,
                        caseId))
                .as("CASE_CLOSED is the vocabulary's existing kind for this; no new kind is invented")
                .isEqualTo(1);
        assertThat(inbox.find(CaseResultTrustConfiguration.RESULT_CONSUMER, eventId)
                        .projectedAt())
                .as("the inbox row says it has been applied, which is what makes a redelivery harmless")
                .isNotNull();
    }

    @Test
    @DisplayName("C05.2b-3b: a determined failure sends the case back to review instead of closing it")
    void aDeterminedFailureSendsTheCaseBackToReview() {
        String eventId = UUID.randomUUID().toString();

        assertThat(consumer.consume(failed(eventId, MERCHANT, 4, "PROVIDER_DECLINED")))
                .isEqualTo(CaseResultConsumer.Disposition.ACCEPTED);

        // docs/domain-model.md:55: 确定失败且金额释放 -> PENDING_REVIEW. The release itself is Commerce's fact and
        // is asserted there (RefundAcceptanceApiTest asserts the reservation really went to zero); what this
        // service owns is its own status and the trajectory row that says why it moved.
        assertThat(caseStatus())
                .as("a failed refund is not a closed case: it goes back to a human, who must authorise again")
                .isEqualTo("PENDING_REVIEW");
        assertThat(jdbc.queryForObject(
                        "SELECT detail FROM case_timeline WHERE case_id = ? ORDER BY sequence DESC LIMIT 1",
                        String.class,
                        caseId))
                .as("the newest trajectory row names the outcome and the reason code Commerce gave")
                .contains("\"outcome\":\"FAILED\"")
                .contains("PROVIDER_DECLINED")
                .contains("PENDING_REVIEW");
        assertThat(jdbc.queryForObject(
                        "SELECT COUNT(*) FROM case_timeline WHERE case_id = ? AND kind = 'CASE_CLOSED'",
                        Integer.class,
                        caseId))
                .as("and nothing claims the case was closed successfully")
                .isZero();
        assertThat(inbox.find(CaseResultTrustConfiguration.RESULT_CONSUMER, eventId)
                        .projectedAt())
                .isNotNull();
    }

    @Test
    @DisplayName("C05.2b-3b: an unknown outcome parks the case in RECONCILING — not closed, nothing released")
    void anUnknownOutcomeParksTheCaseInReconciling() {
        String eventId = UUID.randomUUID().toString();

        assertThat(consumer.consume(unknown(eventId, MERCHANT, 5, "PROVIDER_TIMEOUT")))
                .isEqualTo(CaseResultConsumer.Disposition.ACCEPTED);

        // docs/domain-model.md:55 sends UNKNOWN to RECONCILING rather than to a closure, because "we do not know"
        // releases nothing and settles nothing: the reservation still stands at Commerce and the outcome is still
        // unknown, so a person (or a later reconciliation) has to find out. None of that is the case's to decide,
        // which is why this service only records where the case now stands.
        assertThat(caseStatus()).isEqualTo("RECONCILING");
        assertThat(jdbc.queryForObject(
                        "SELECT detail FROM case_timeline WHERE case_id = ? ORDER BY sequence DESC LIMIT 1",
                        String.class,
                        caseId))
                .as("the trajectory names the outcome and keeps Commerce's reason code beside it")
                .contains("\"outcome\":\"UNKNOWN\"")
                .contains("PROVIDER_TIMEOUT")
                .contains("RECONCILING");
        assertThat(jdbc.queryForObject(
                        "SELECT COUNT(*) FROM case_timeline WHERE case_id = ? AND kind = 'CASE_CLOSED'",
                        Integer.class,
                        caseId))
                .as("an unknown outcome must not be dressed up as a closure of any kind")
                .isZero();
        assertThat(CaseStatus.of(caseStatus()).acceptsNewInput())
                .as("and the input stays frozen: the money may still move, so nothing may be re-argued yet")
                .isFalse();
        assertThat(inbox.find(CaseResultTrustConfiguration.RESULT_CONSUMER, eventId)
                        .projectedAt())
                .isNotNull();
    }

    @Test
    @DisplayName("C05.2b-3b: a late lower version moves nothing — and is not silently dropped either")
    void aLateLowerVersionIsRecordedWithoutMovingTheCase() {
        String firstEventId = UUID.randomUUID().toString();
        String lateEventId = UUID.randomUUID().toString();

        // The determined failure at Commerce version 4 arrives first and sends the case back to review.
        assertThat(consumer.consume(failed(firstEventId, MERCHANT, 4, "PROVIDER_DECLINED")))
                .isEqualTo(CaseResultConsumer.Disposition.ACCEPTED);
        String statusAfterTheNewerFact = caseStatus();
        long versionAfterTheNewerFact =
                jdbc.queryForObject("SELECT version FROM aftersale_case WHERE case_id = ?", Long.class, caseId);
        int rowsAfterTheNewerFact =
                jdbc.queryForObject("SELECT COUNT(*) FROM case_timeline WHERE case_id = ?", Integer.class, caseId);

        // A different event carrying the same operation's *older* fact (version 3) arrives afterwards: the
        // out-of-order delivery that at-least-once delivery is allowed to produce.
        assertThat(consumer.consume(failed(lateEventId, MERCHANT, 3, "PROVIDER_DECLINED_EARLIER")))
                .isEqualTo(CaseResultConsumer.Disposition.ACCEPTED);

        assertThat(caseStatus())
                .as("the case already knows a newer fact about this operation, so an older one cannot move it")
                .isEqualTo(statusAfterTheNewerFact);
        assertThat(jdbc.queryForObject("SELECT version FROM aftersale_case WHERE case_id = ?", Long.class, caseId))
                .as("nothing about the case moved, so its version must not have moved either")
                .isEqualTo(versionAfterTheNewerFact);
        assertThat(jdbc.queryForObject(
                        "SELECT detail FROM case_timeline WHERE case_id = ? ORDER BY sequence DESC LIMIT 1",
                        String.class,
                        caseId))
                .as("the older fact is still recorded: an operator has to be able to see that it arrived and was"
                        + " ignored, otherwise a real ordering bug looks exactly like a delivery that never"
                        + " happened")
                .contains("\"ignored_as_stale\":true")
                .contains("\"outcome\":\"FAILED\"")
                .contains("PROVIDER_DECLINED_EARLIER");
        assertThat(jdbc.queryForObject("SELECT COUNT(*) FROM case_timeline WHERE case_id = ?", Integer.class, caseId))
                .as("the trace is one appended row, not a rewrite of the history behind it")
                .isEqualTo(rowsAfterTheNewerFact + 1);
        assertThat(inbox.find(CaseResultTrustConfiguration.RESULT_CONSUMER, lateEventId)
                        .projectedAt())
                .as("and the row has been dealt with: projected_at means the case reflects the decision, which"
                        + " here was to keep the newer fact")
                .isNotNull();
    }

    @Test
    @DisplayName("C05.2b-3b: a refused result leaves the case exactly as it was — no trace, no movement")
    void aRefusedResultLeavesTheCaseUntouched() {
        String eventId = UUID.randomUUID().toString();
        String tampered = succeeded(eventId, MERCHANT, 3).replace("2599", "1");
        String statusBefore = caseStatus();
        long versionBefore =
                jdbc.queryForObject("SELECT version FROM aftersale_case WHERE case_id = ?", Long.class, caseId);
        int timelineBefore =
                jdbc.queryForObject("SELECT COUNT(*) FROM case_timeline WHERE case_id = ?", Integer.class, caseId);

        assertThatThrownBy(() -> consumer.consume(tampered))
                .isInstanceOf(CaseResultVerifier.RefusedEventException.class);

        // b-3a asserted the inbox half of this ("a result that failed verification is not a fact"). C05.2b-3b adds
        // the other half, because from here on an accepted result *moves* the case: "nothing happened" is now a
        // claim that has to be asserted rather than assumed.
        assertThat(caseStatus()).isEqualTo(statusBefore);
        assertThat(jdbc.queryForObject("SELECT version FROM aftersale_case WHERE case_id = ?", Long.class, caseId))
                .as("a refused result cannot have moved the case, so it cannot have moved its version either")
                .isEqualTo(versionBefore);
        assertThat(jdbc.queryForObject("SELECT COUNT(*) FROM case_timeline WHERE case_id = ?", Integer.class, caseId))
                .as("and it leaves no trajectory row claiming an outcome arrived")
                .isEqualTo(timelineBefore);
    }

    @Test
    @DisplayName("C05.2b-3b: two deliveries of the same version cannot close the case twice")
    void twoDeliveriesOfTheSameVersionCannotCloseTheCaseTwice() throws InterruptedException {
        String firstEventId = UUID.randomUUID().toString();
        String secondEventId = UUID.randomUUID().toString();
        long versionBefore =
                jdbc.queryForObject("SELECT version FROM aftersale_case WHERE case_id = ?", Long.class, caseId);
        CaseResultConsumer.Disposition[] dispositions = new CaseResultConsumer.Disposition[2];
        Throwable[] failures = new Throwable[2];

        Thread first =
                new Thread(() -> consumeRecording(succeeded(firstEventId, MERCHANT, 6), dispositions, failures, 0));
        Thread second =
                new Thread(() -> consumeRecording(succeeded(secondEventId, MERCHANT, 6), dispositions, failures, 1));
        first.start();
        second.start();
        // Joining both threads is what makes the reads below safe: it creates the happens-before edge between the
        // writes the workers did and this thread's assertions on them.
        first.join();
        second.join();

        assertThat(failures[0])
                .as("a delivery colliding with another must not blow up")
                .isNull();
        assertThat(failures[1])
                .as("a delivery colliding with another must not blow up")
                .isNull();
        assertThat(dispositions[0])
                .as("both events are new, so both are claimed; what they may not both do is move the case")
                .isEqualTo(CaseResultConsumer.Disposition.ACCEPTED);
        assertThat(dispositions[1]).isEqualTo(CaseResultConsumer.Disposition.ACCEPTED);

        assertThat(caseStatus())
                .as("both events say the same thing at the same version, so the case closes exactly once")
                .isEqualTo("CLOSED_SUCCESS");
        assertThat(jdbc.queryForObject(
                        "SELECT COUNT(*) FROM case_timeline WHERE case_id = ? AND kind = 'CASE_CLOSED'",
                        Integer.class,
                        caseId))
                .as("one operation, one closure: the delivery that lost must not add a second one")
                .isEqualTo(1);
        assertThat(jdbc.queryForObject("SELECT version FROM aftersale_case WHERE case_id = ?", Long.class, caseId))
                .as("the case moved once, not twice")
                .isEqualTo(versionBefore + 1);
        // The losing delivery is accounted for in exactly one of the two honest ways, depending on whether it read
        // the operation's applied version before or after the winner committed: recorded as stale, or left visibly
        // unapplied because its guarded UPDATE matched no row. What it must never be is a second closure.
        int staleTraces = jdbc.queryForObject(
                "SELECT COUNT(*) FROM case_timeline WHERE case_id = ? AND detail LIKE '%ignored_as_stale%'",
                Integer.class, caseId);
        int leftUnapplied = jdbc.queryForObject(
                "SELECT COUNT(*) FROM case_result_inbox WHERE case_id = ? AND projected_at IS NULL",
                Integer.class,
                caseId);
        assertThat(staleTraces + leftUnapplied)
                .as("the delivery that did not win is either recorded as stale or left visibly unapplied")
                .isEqualTo(1);
    }

    // ------------------------------------------------------------------ fixtures

    /** A signed result, as Commerce's C05.2b-1 outbox writes it. */
    /**
     * Runs one {@code consume} on a worker thread, recording what it returned or threw (C05.2b-3b slice ⑤).
     *
     * <p>The refusals this consumer raises are exceptions on purpose, so a concurrent test has to catch them
     * inside the worker: letting one escape would report a lost race as a broken test.
     */
    private void consumeRecording(
            String message, CaseResultConsumer.Disposition[] dispositions, Throwable[] failures, int slot) {
        try {
            dispositions[slot] = consumer.consume(message);
        } catch (Throwable error) {
            failures[slot] = error;
        }
    }

    private String succeeded(String eventId, String merchantId, long aggregateVersion) {
        return resultEnvelope(
                eventId,
                merchantId,
                CoreEnvelope.SUCCEEDED,
                2599,
                "prv-b3a-1",
                null,
                aggregateVersion,
                "commerce-service-demo-key",
                producerKey(),
                operationId);
    }

    /** A signed unknown outcome, as Commerce's outbox writes it when the provider would not say. */
    private String unknown(String eventId, String merchantId, long aggregateVersion, String reasonCode) {
        return resultEnvelope(
                eventId,
                merchantId,
                CoreEnvelope.UNKNOWN,
                2599,
                null,
                reasonCode,
                aggregateVersion,
                "commerce-service-demo-key",
                producerKey());
    }

    /** A signed determined failure, as Commerce's outbox writes it after it released the reservation. */
    private String failed(String eventId, String merchantId, long aggregateVersion, String reasonCode) {
        return resultEnvelope(
                eventId,
                merchantId,
                CoreEnvelope.FAILED,
                2599,
                null,
                reasonCode,
                aggregateVersion,
                "commerce-service-demo-key",
                producerKey());
    }

    /**
     * A correctly signed result whose payload state is written by hand.
     *
     * <p>Needed only for {@link #anUnknownStateIsRefusedAndRecorded}: {@link CoreEnvelope#resultPayload} refuses
     * a state outside the contract, so the shared helper cannot express the one document that path exists for.
     * The event type is a real one, because the point is a signature that holds over an unreadable payload.
     */
    private String aCorrectlySignedResultWithState(
            String eventId, String state, long amountMinor, long aggregateVersion) {
        ObjectNode payload = MAPPER.createObjectNode();
        payload.put("operation_id", operationId);
        payload.put(
                "line_id",
                jdbc.queryForObject("SELECT line_id FROM aftersale_case WHERE case_id = ?", String.class, caseId));
        payload.put("state", state);
        payload.put("amount_minor", amountMinor);
        payload.put("provider_ref", "prv-state-test");
        payload.putNull("reason_code");
        payload.put("aggregate_version", aggregateVersion);
        return CoreEnvelope.canonical(CoreEnvelope.sign(
                eventId,
                CoreEnvelope.resultEventType(CoreEnvelope.SUCCEEDED),
                MERCHANT,
                Instant.now(),
                payload,
                null,
                TRACEPARENT,
                "commerce-service-demo-key",
                producerKey()));
    }

    private String resultEnvelope(
            String eventId,
            String merchantId,
            String state,
            long amountMinor,
            String providerRef,
            String reasonCode,
            long aggregateVersion,
            String signingKeyId,
            PrivateKey key) {
        return resultEnvelope(
                eventId,
                merchantId,
                state,
                amountMinor,
                providerRef,
                reasonCode,
                aggregateVersion,
                signingKeyId,
                key,
                operationId);
    }

    private String resultEnvelope(
            String eventId,
            String merchantId,
            String state,
            long amountMinor,
            String providerRef,
            String reasonCode,
            long aggregateVersion,
            String signingKeyId,
            PrivateKey key,
            String resultOperationId) {
        ObjectNode payload = CoreEnvelope.resultPayload(
                resultOperationId,
                jdbc.queryForObject("SELECT line_id FROM aftersale_case WHERE case_id = ?", String.class, caseId),
                state,
                amountMinor,
                providerRef,
                reasonCode,
                aggregateVersion);
        ObjectNode envelope = CoreEnvelope.sign(
                eventId,
                CoreEnvelope.resultEventType(state),
                merchantId,
                Instant.now(),
                payload,
                null,
                TRACEPARENT,
                signingKeyId,
                key);
        return CoreEnvelope.canonical(envelope);
    }

    private String caseStatus() {
        return jdbc.queryForObject("SELECT status FROM aftersale_case WHERE case_id = ?", String.class, caseId);
    }

    // ------------------------------------------------------------------ getting a case to EXECUTING

    private String token(String subject, Role role, String customerId) {
        return new JwtCodec(secret, Duration.ofHours(1))
                .issue(new AuthenticatedPrincipal(subject, MERCHANT, role, customerId), Instant.now());
    }

    private String serviceToken() {
        return new JwtCodec(secret, Duration.ofHours(1)).issueServiceToken("agent-service", Instant.now());
    }

    /** Open, propose, approve and dispatch: the four existing steps, driven through their real entry points. */
    private String executingCase() {
        String opened = openCase();
        deliverProposal(opened);
        String authorizationId = jdbc.queryForObject(
                "SELECT authorization_id FROM case_authorization WHERE case_id = ?", String.class, opened);
        long caseVersion =
                jdbc.queryForObject("SELECT version FROM aftersale_case WHERE case_id = ?", Long.class, opened);
        decide(opened, caseVersion, authorizationId);

        AuthorizationConsumptionService.Consumption consumed =
                consumption.consume(authorizations.findAwaitingDispatch(1).get(0));
        assertThat(consumed.dispatched()).as("the fixture must reach EXECUTING").isTrue();
        return opened;
    }

    private String openCase() {
        String lineId = String.valueOf(++lineCounter);
        String body = rest.post()
                .uri("/api/v1/cases")
                .header("Authorization", "Bearer " + customer())
                .header("Idempotency-Key", "result-case-" + lineId)
                .contentType(MediaType.APPLICATION_JSON)
                .body("{\"line_id\":\"" + lineId + "\",\"description\":\"退款诉求\",\"requested_actions\":[\"REFUND\"]}")
                .exchange()
                .expectStatus()
                .isCreated()
                .expectBody(String.class)
                .returnResult()
                .getResponseBody();
        return MAPPER.readTree(body).get("case_id").stringValue();
    }

    private void deliverProposal(String caseId) {
        ObjectNode proposal = MAPPER.createObjectNode();
        proposal.put("schema_version", 2);
        proposal.put("proposal_id", UUID.randomUUID().toString());
        proposal.put("run_id", RUN);
        proposal.put("case_id", caseId);
        proposal.put("input_revision", 1);
        proposal.put("case_type", "LOGISTICS");
        proposal.put("recommended_action", "REFUND");
        proposal.put("summary", "承运商判定丢失，按 2026.09 政策全额退款");
        proposal.put("suggested_amount_minor", 2000);
        proposal.putArray("reason_codes").add("CARRIER_LOST");
        proposal.putArray("policy_refs").add(citation());

        ObjectNode body = MAPPER.createObjectNode();
        body.put("callback_id", "result-proposal-" + caseId);
        body.put("run_id", RUN);
        body.put("input_revision", 1);
        body.put("kind", "PROPOSAL");
        body.set("payload", proposal);
        body.put("traceparent", TRACEPARENT);
        rest.post()
                .uri("/internal/v1/cases/" + caseId + "/agent-callbacks")
                .header("Authorization", "Bearer " + serviceToken())
                .contentType(MediaType.APPLICATION_JSON)
                .body(body.toString())
                .exchange()
                .expectStatus()
                .isOk();
    }

    private void decide(String caseId, long caseVersion, String authorizationId) {
        ObjectNode body = MAPPER.createObjectNode();
        body.put("authorization_id", authorizationId);
        body.put("authorization_version", 1);
        body.put("decision", "APPROVE");
        body.put("reason", "物流结论与政策一致，证据充分");
        rest.post()
                .uri("/api/v1/cases/" + caseId + "/reviews")
                .header("Authorization", "Bearer " + reviewer())
                .header("If-Match", "\"" + caseVersion + "\"")
                .contentType(MediaType.APPLICATION_JSON)
                .body(body.toString())
                .exchange()
                .expectStatus()
                .isOk();
    }

    private String customer() {
        return token("demo-customer", Role.CUSTOMER, CUSTOMER);
    }

    private String reviewer() {
        return token("demo-reviewer", Role.REVIEWER, null);
    }

    private ObjectNode citation() {
        return jdbc.query(
                "SELECT position, rule_id, title, text FROM policy_rule WHERE bundle_id = ? AND rule_id = ?",
                resultSet -> {
                    assertThat(resultSet.next()).isTrue();
                    PolicyRule rule = PolicyRule.from(
                            BUNDLE,
                            resultSet.getInt("position"),
                            resultSet.getString("rule_id"),
                            resultSet.getString("title"),
                            resultSet.getString("text"));
                    ObjectNode node = MAPPER.createObjectNode();
                    node.put("bundle_id", BUNDLE);
                    node.put("version", VERSION);
                    node.put("rule_id", "R-LOST-001");
                    node.put("chunk_id", rule.chunkId());
                    node.put("content_hash", rule.contentHash());
                    return node;
                },
                BUNDLE,
                "R-LOST-001");
    }
}
