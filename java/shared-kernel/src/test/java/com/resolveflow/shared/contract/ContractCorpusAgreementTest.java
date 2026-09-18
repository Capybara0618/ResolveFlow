package com.resolveflow.shared.contract;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

import java.nio.charset.StandardCharsets;
import java.security.PrivateKey;
import java.security.PublicKey;
import java.util.LinkedHashMap;
import java.util.LinkedHashSet;
import java.util.Map;
import java.util.Set;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import tools.jackson.databind.JsonNode;
import tools.jackson.databind.ObjectMapper;

/**
 * The cross-language half of T02: Java reproduces the frozen corpus values byte for byte.
 *
 * <p>docs/contracts.md:17 requires T02 to freeze both the signing inputs and the resulting bytes.
 * Python wrote them ({@code scripts/contracts_freeze.py}); this test recomputes every one of them from
 * the same {@code contracts/fixtures/**} corpus with the independent Java implementation. If the two
 * implementations ever disagree about escaping, key ordering or the hashed field set, this fails on
 * the exact fixture that exposed it instead of failing later in production.
 *
 * <p>The corpus is read from disk rather than restated here on purpose: a Java copy of the fixtures
 * would pass against itself and prove nothing.
 */
class ContractCorpusAgreementTest {

    private static final ObjectMapper MAPPER = new ObjectMapper();

    private static Map<String, String> frozen(String section) {
        JsonNode node = ContractFixtures.expectedHashes().get(section);
        Map<String, String> values = new LinkedHashMap<>();
        node.properties().forEach(entry -> values.put(entry.getKey(), entry.getValue().stringValue()));
        return values;
    }

    /** Resolve an envelope and inline the payload its {@code payload_ref} names. */
    private static JsonNode resolveEnvelope(JsonNode corpus, String name, Map<String, String> values) {
        JsonNode entry = corpus.get("message_envelope").get(name);
        var instance = ContractFixtures.resolveInstance(entry, corpus);
        String reference = entry.get("payload_ref").stringValue();
        if (!reference.startsWith("execution_command.") && !reference.startsWith("event_payload.")) {
            throw new ContractFixtures.FixtureException("envelope " + name + " references " + reference);
        }
        JsonNode payload = ContractFixtures.substituteValues(
                ContractFixtures.resolveInstance(ContractFixtures.lookup(corpus, reference), corpus), values);
        instance.set("payload", payload);
        return instance;
    }

    @Test
    @DisplayName("Every execution payload hash matches the frozen digest")
    void executionPayloadHashesMatch() {
        JsonNode payloads = ContractFixtures.canonicalCorpus().get("execution_payloads");
        Map<String, String> expected = frozen("execution_payload_hashes");

        assertThat(expected).isNotEmpty();
        for (Map.Entry<String, JsonNode> entry : payloads.properties()) {
            String actual = CanonicalJson.payloadHash(ContractFixtures.stripAnnotations(entry.getValue()));
            assertThat(actual)
                    .as("payload hash of %s", entry.getKey())
                    .isEqualTo(expected.get(entry.getKey()));
        }
    }

    @Test
    @DisplayName("Every content hash and canonical document matches the frozen value")
    void contentHashesAndCanonicalDocumentsMatch() {
        JsonNode canonical = ContractFixtures.canonicalCorpus();
        Map<String, String> expectedHashes = frozen("content_hashes");
        Map<String, String> expectedDocuments = frozen("canonical_documents");

        canonical.get("content_hashes")
                .properties()
                .forEach(entry -> assertThat(CanonicalJson.contentHash(ContractFixtures.stripAnnotations(entry.getValue())))
                        .as("content hash of %s", entry.getKey())
                        .isEqualTo(expectedHashes.get(entry.getKey())));

        canonical.get("unicode_documents")
                .properties()
                .forEach(entry -> assertThat(CanonicalJson.canonicalize(ContractFixtures.stripAnnotations(entry.getValue())))
                        .as("canonical text of %s", entry.getKey())
                        .isEqualTo(expectedDocuments.get(entry.getKey())));
    }

    @Test
    @DisplayName("The UTF-16 ordering fixture really distinguishes code-unit from code-point order")
    void utf16OrderingFixtureIsDiscriminating() {
        // A guard on the guard: if this document ever stopped containing a supplementary
        // character before a BMP one, the ordering test above would pass for the wrong reason.
        String canonical = CanonicalJson.canonicalize(ContractFixtures.stripAnnotations(
                ContractFixtures.canonicalCorpus().get("content_hashes").get("utf16-key-ordering")));

        int supplementary = canonical.indexOf("\uD800\uDC00");
        int privateUse = canonical.indexOf("\uE000");
        int replacement = canonical.indexOf("\uFFFD");
        assertThat(supplementary).isGreaterThan(0);
        assertThat(privateUse).isGreaterThan(0);
        assertThat(replacement).isGreaterThan(0);
        assertThat(supplementary).isGreaterThan(privateUse).isGreaterThan(replacement);
    }

    @Test
    @DisplayName("Signing inputs and signatures match the frozen bytes, and the frozen signature verifies")
    void signingInputsAndSignaturesMatch() {
        JsonNode corpus = ContractFixtures.validCorpus();
        Map<String, String> values = ContractFixtures.placeholderValues();
        Map<String, String> expectedInputs = frozen("signing_inputs");
        Map<String, String> expectedSignatures = frozen("event_signatures");

        JsonNode keys = ContractFixtures.expectedHashes().get("signing_keys");
        PrivateKey privateKey =
                EventSignature.privateKeyFromPkcs8(ContractFixtures.decodeBase64(keys.get("private_key_pkcs8_base64").stringValue()));
        PublicKey publicKey =
                EventSignature.publicKeyFromSpki(ContractFixtures.decodeBase64(keys.get("public_key_spki_base64").stringValue()));

        assertThat(expectedInputs).isNotEmpty();
        for (Map.Entry<String, JsonNode> entry : corpus.get("message_envelope").properties()) {
            String name = entry.getKey();
            JsonNode envelope = resolveEnvelope(corpus, name, values);

            String signingInput = new String(EventSignature.signingInputBytes(envelope), StandardCharsets.UTF_8);
            assertThat(signingInput).as("signing input of %s", name).isEqualTo(expectedInputs.get(name));

            String frozenSignature = expectedSignatures.get(name);
            if (frozenSignature == null) {
                // An unsigned result event: commerce and fulfillment publish state changes without a
                // case signature (docs/contracts.md:121). Its signing input is still fixed above.
                assertThat(envelope.has("signing_key_id")).isFalse();
                assertThat(envelope.has("signature")).isFalse();
                continue;
            }

            assertThat(EventSignature.sign(envelope, privateKey))
                    .as("signature of %s", name)
                    .isEqualTo(frozenSignature);
            // Java also verifies Python's bytes, not just its own re-derivation.
            EventSignature.verify(envelope, frozenSignature, publicKey);
        }
    }

    @Test
    @DisplayName("The frozen placeholder table agrees with the corpus that refers to it")
    void placeholderTableAgreesWithTheCorpus() {
        JsonNode corpus = ContractFixtures.validCorpus();
        Map<String, String> values = ContractFixtures.placeholderValues();
        Map<String, String> expectedSignatures = frozen("event_signatures");

        Set<String> referenced = new LinkedHashSet<>();
        collectPlaceholders(corpus, referenced);

        // Every token the corpus uses resolves, and every frozen token has a reader: the generator
        // enforces the same rule, and this side proves the Java reader sees the same table.
        assertThat(referenced).isSubsetOf(values.keySet());
        assertThat(values.keySet()).isSubsetOf(referenced);

        // A signed envelope's placeholder must name the signature that was actually frozen.
        corpus.get("message_envelope")
                .properties()
                .forEach(entry -> {
                    JsonNode placeholder = entry.getValue().get("_signature_placeholder");
                    if (placeholder != null) {
                        assertThat(values.get(placeholder.stringValue()))
                                .as("placeholder %s", placeholder.stringValue())
                                .isEqualTo(expectedSignatures.get(entry.getKey()));
                    }
                });
    }

    private static void collectPlaceholders(JsonNode node, Set<String> found) {
        if (node.isString()) {
            if (node.stringValue().startsWith("PLACEHOLDER_")) {
                found.add(node.stringValue());
            }
            return;
        }
        if (node.isObject()) {
            node.properties().forEach(entry -> {
                if (entry.getKey().startsWith("PLACEHOLDER_")) {
                    found.add(entry.getKey());
                }
                collectPlaceholders(entry.getValue(), found);
            });
            return;
        }
        if (node.isArray()) {
            node.forEach(item -> collectPlaceholders(item, found));
        }
    }

    @Test
    @DisplayName("Payloads the corpus marks invalid are refused by the Java hash")
    void invalidPayloadsAreRefused() {
        JsonNode invalid = ContractFixtures.canonicalCorpus().get("invalid_payloads");
        assertThat(invalid.size()).isGreaterThanOrEqualTo(3);

        invalid.properties().forEach(entry -> assertThatThrownBy(
                        () -> CanonicalJson.payloadHash(ContractFixtures.stripAnnotations(entry.getValue())))
                .as("invalid payload %s", entry.getKey())
                .isInstanceOf(CanonicalJson.CanonicalizationException.class));
    }

    @Test
    @DisplayName("The negative corpus is present, self-documented and shared with the Python schema check")
    void negativeCorpusIsSelfDocumented() {
        JsonNode reject = ContractFixtures.rejectCorpus();
        Set<String> sections = new LinkedHashSet<>();
        reject.properties().forEach(entry -> {
            if (entry.getKey().startsWith("_")) {
                return;
            }
            sections.add(entry.getKey());
            entry.getValue().properties().forEach(fixture -> {
                JsonNode why = fixture.getValue().get("why");
                assertThat(why)
                        .as("%s.%s must explain why it has to be refused", entry.getKey(), fixture.getKey())
                        .isNotNull();
                assertThat(why.stringValue()).isNotBlank();
                assertThat(fixture.getValue().get("instance"))
                        .as("%s.%s must carry the instance to refuse", entry.getKey(), fixture.getKey())
                        .isNotNull();
            });
        });

        // The sections docs/contracts.md fixes: the command, the envelope and its result payloads,
        // the proposal, the harness manifest, and the error body.
        assertThat(sections)
                .containsExactlyInAnyOrder(
                        "execution_command",
                        "event_envelope",
                        "result_event_payload",
                        "agent_proposal",
                        "harness_manifest",
                        "error_body");
    }

    @Test
    @DisplayName("A fixture reference that does not resolve fails loudly instead of being skipped")
    void danglingReferencesFail() {
        assertThatThrownBy(() -> ContractFixtures.lookup(MAPPER.createObjectNode(), "execution_command.refund"))
                .isInstanceOf(ContractFixtures.FixtureException.class);

        // A placeholder nested inside an array is resolved, and reported when it has no frozen
        // value, rather than being copied through as a literal token.
        JsonNode nested = MAPPER.readTree("{\"refs\":[\"PLACEHOLDER_NOWHERE\"]}");
        assertThatThrownBy(() -> ContractFixtures.substituteValues(nested, Map.of()))
                .isInstanceOf(ContractFixtures.FixtureException.class)
                .hasMessageContaining("PLACEHOLDER_NOWHERE");
    }
}