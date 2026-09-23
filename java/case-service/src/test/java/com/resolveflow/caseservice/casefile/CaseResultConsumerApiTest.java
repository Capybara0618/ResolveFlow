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
                .as("the signed bytes are kept verbatim, which is what makes the verification reproducible")
                .contains(eventId);
        assertThat(stored.signature()).isNotBlank();
        assertThat(stored.projectedAt())
                .as("projection onto the case state machine is C05.2b-3b's step, not this one")
                .isNull();
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
    @DisplayName(
            "boundary of C05.2b-3a: an accepted RefundSucceeded leaves the case EXECUTING, because projection is C05.2b-3b")
    void anAcceptedResultIsNotProjectedYet() {
        String eventId = UUID.randomUUID().toString();
        long versionBefore =
                jdbc.queryForObject("SELECT version FROM aftersale_case WHERE case_id = ?", Long.class, caseId);

        assertThat(consumer.consume(succeeded(eventId, MERCHANT, 3)))
                .isEqualTo(CaseResultConsumer.Disposition.ACCEPTED);

        // This assertion is the sub-step's boundary, stated out loud rather than left to be discovered: the
        // result is durably received and *not* projected. C05.2b-3b owns the transition to CLOSED_SUCCESS and
        // the timeline row that records the outcome, and it will consume the inbox row this step left behind.
        assertThat(caseStatus())
                .as("projection is C05.2b-3b's step; this sub-step only lands the fact durably")
                .isEqualTo("EXECUTING");
        assertThat(jdbc.queryForObject("SELECT version FROM aftersale_case WHERE case_id = ?", Long.class, caseId))
                .as("nothing about the case moved, so nothing can have been projected")
                .isEqualTo(versionBefore);
        assertThat(jdbc.queryForObject(
                        "SELECT COUNT(*) FROM case_timeline WHERE case_id = ? AND kind = 'CASE_CLOSED'",
                        Integer.class,
                        caseId))
                .isZero();
        assertThat(inbox.find(CaseResultTrustConfiguration.RESULT_CONSUMER, eventId)
                        .projectedAt())
                .isNull();
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

    // ------------------------------------------------------------------ fixtures

    /** A signed result, as Commerce's C05.2b-1 outbox writes it. */
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
