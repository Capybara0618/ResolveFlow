package com.resolveflow.shared.core;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

import com.resolveflow.shared.contract.CanonicalJson;
import com.resolveflow.shared.contract.ContractFixtures;
import com.resolveflow.shared.contract.EventSignature;
import java.util.ArrayList;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Map;
import java.util.Set;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import tools.jackson.databind.JsonNode;
import tools.jackson.databind.ObjectMapper;

/**
 * The Java half of the core cross-language evidence.
 *
 * <p>Shapes alone would be weak: two implementations can agree on field names and still hash or sign
 * different bytes. These tests recompute the values Python froze in {@code
 * contracts/core/fixtures/expected.json} from the same fixtures — the payload hash and the Ed25519
 * signature — so agreement is asserted on bytes, not on structure.
 *
 * <p>Schema validation itself lives on the Python side (this module has no JSON Schema validator);
 * what Java proves here is that its records match the schema's property sets, that every positive
 * fixture deserialises and round-trips, and that the two languages produce identical digests and
 * signatures for the core wire.
 */
class CoreContractTest {

    private static final ObjectMapper MAPPER = new ObjectMapper();

    /** Model class -> the core schema URN whose properties it must match. */
    private static Map<Class<?>, String> schemas() {
        return Map.of(
                CoreContract.CoreRefundCommand.class, "urn:resolveflow:core:refund-command:v2",
                CoreContract.CoreEnvelope.class, "urn:resolveflow:core:event-envelope:v2",
                CoreContract.CoreAgentProposal.class, "urn:resolveflow:core:agent-proposal:v2");
    }

    private static Map<String, String> schemaFiles() {
        return Map.of(
                "urn:resolveflow:core:refund-command:v2", "contracts/core/refund-command.schema.json",
                "urn:resolveflow:core:event-envelope:v2", "contracts/core/event-envelope.schema.json",
                "urn:resolveflow:core:agent-proposal:v2", "contracts/core/agent-proposal.schema.json");
    }

    private static JsonNode schema(String urn) {
        return ContractFixtures.load(schemaFiles().get(urn));
    }

    private static Map<Class<?>, String> sections() {
        return Map.of(
                CoreContract.CoreRefundCommand.class, "execution_commands",
                CoreContract.CoreEnvelope.class, "message_envelopes",
                CoreContract.CoreAgentProposal.class, "agent_proposals");
    }

    private static <T> T bind(String section, String name, Class<T> type) {
        return MAPPER.readValue(CoreFixtures.instance(section, name).toString(), type);
    }

    @Test
    @DisplayName("every core record matches the property set of the schema it belongs to")
    void recordsMatchTheirSchema() {
        schemas().forEach((type, urn) -> {
            Set<String> declared = new LinkedHashSet<>();
            for (var component : type.getRecordComponents()) {
                declared.add(wireName(type, component.getName()));
            }
            Set<String> inSchema = new LinkedHashSet<>();
            schema(urn).get("properties").properties().forEach(entry -> inSchema.add(entry.getKey()));
            assertThat(declared)
                    .as("%s must declare exactly the members of %s", type.getSimpleName(), urn)
                    .containsExactlyInAnyOrderElementsOf(inSchema);
        });
    }

    /**
     * The wire name of a record component: its {@code @JsonProperty} when present, its field name
     * otherwise. Reading the annotation is the point — a component renamed without its annotation
     * would otherwise silently keep matching the schema.
     */
    private static String wireName(Class<?> type, String component) {
        for (var item : type.getRecordComponents()) {
            if (item.getName().equals(component)) {
                var annotation = item.getAccessor().getAnnotation(com.fasterxml.jackson.annotation.JsonProperty.class);
                return annotation == null ? component : annotation.value();
            }
        }
        throw new IllegalStateException(type.getSimpleName() + " has no component named " + component);
    }

    @Test
    @DisplayName("every positive core fixture deserialises into its record and round-trips")
    void everyPositiveFixtureBindsAndRoundTrips() {
        // The round trip is the shape-level cross-language evidence Java can produce without a JSON
        // Schema validator: if reading a schema-valid fixture and writing it back changes anything,
        // then Java's own output would not be the document its schema accepts. That is not
        // hypothetical - this test caught the records emitting an explicit `null` for an absent
        // optional member, which the core schema refuses (the wire says "absent" by omitting it).
        sections().forEach((type, section) -> {
            var names = CoreFixtures.names(section);
            assertThat(names).as("section %s must contain fixtures", section).isNotEmpty();
            for (String name : names) {
                JsonNode instance = CoreFixtures.instance(section, name);
                Object bound = MAPPER.readValue(instance.toString(), type);
                JsonNode written = MAPPER.readTree(MAPPER.writeValueAsString(bound));
                assertThat(written)
                        .as("%s.%s must survive a bind/serialise round trip", section, name)
                        .isEqualTo(instance);
                assertNoPlaceholder(instance, section + "." + name);
            }
        });
    }

    private static void assertNoPlaceholder(JsonNode node, String where) {
        List<String> leftovers = new ArrayList<>();
        collectPlaceholders(node, where, leftovers);
        assertThat(leftovers).as("%s kept unresolved placeholder values", where).isEmpty();
    }

    private static void collectPlaceholders(JsonNode node, String path, List<String> found) {
        if (CoreFixtures.isPlaceholder(node)) {
            found.add(path);
            return;
        }
        if (node.isObject()) {
            node.properties()
                    .forEach(entry -> collectPlaceholders(entry.getValue(), path + "." + entry.getKey(), found));
            return;
        }
        if (node.isArray()) {
            int index = 0;
            for (JsonNode item : node) {
                collectPlaceholders(item, path + "[" + index++ + "]", found);
            }
        }
    }

    @Test
    @DisplayName("Java reproduces the payload hash and canonical bytes Python froze")
    void javaReproducesTheFrozenPayloadHash() {
        JsonNode command = CoreFixtures.instance("execution_commands", "lost_parcel_full_line");
        String digest = CanonicalJson.payloadHash(command);
        assertThat(digest)
                .as("the core command hash must equal the frozen Python value")
                .isEqualTo(CoreFixtures.payloadHashes().get("refundCommandLostParcel"));

        // The bytes, not only the digest: a different normalisation could still collide on a hash
        // value only by accident, but comparing the canonical JSON shows exactly what both sides hash.
        var hashedMembers = MAPPER.createObjectNode();
        command.properties().forEach(entry -> {
            if (!"payload_hash".equals(entry.getKey())) {
                hashedMembers.set(entry.getKey(), entry.getValue());
            }
        });
        assertThat(CanonicalJson.canonicalize(hashedMembers))
                .as("the canonical bytes must equal the frozen Python value")
                .isEqualTo(CoreFixtures.canonicalPayloads().get("refundCommandLostParcel"));
    }

    @Test
    @DisplayName("Java verifies the core signatures Python froze, using the core signing input")
    void javaVerifiesTheFrozenCoreSignatures() {
        var publicKey =
                EventSignature.publicKeyFromSpki(ContractFixtures.decodeBase64(CoreFixtures.publicKeySpkiBase64()));
        Map<String, String> signatures = CoreFixtures.eventSignatures();
        Map<String, String> inputs = CoreFixtures.signingInputs();
        assertThat(signatures).isNotEmpty();
        signatures.forEach((name, signature) -> {
            JsonNode envelope = CoreFixtures.instance("message_envelopes", name);
            CoreEventSignature.verify(envelope, signature, publicKey);
            assertThat(new String(
                            CoreEventSignature.signingInputBytes(envelope), java.nio.charset.StandardCharsets.UTF_8))
                    .as("the signing input of %s must equal the frozen bytes", name)
                    .isEqualTo(inputs.get(name));
        });
    }

    @Test
    @DisplayName("the compat signer cannot verify a core envelope, which is why core has its own")
    void theCompatSignerDoesNotCoverTheCoreEnvelope() {
        var publicKey =
                EventSignature.publicKeyFromSpki(ContractFixtures.decodeBase64(CoreFixtures.publicKeySpkiBase64()));
        JsonNode envelope = CoreFixtures.instance("message_envelopes", "refund_succeeded");
        String coreSignature = CoreFixtures.eventSignatures().get("refund_succeeded");
        CoreEventSignature.verify(envelope, coreSignature, publicKey);
        assertThatThrownBy(() -> EventSignature.verify(envelope, coreSignature, publicKey))
                .as("the compat signing input injects aggregate_* and omits topic")
                .isInstanceOf(EventSignature.EventSignatureException.class);
    }

    @Test
    @DisplayName("Java signs a core envelope to the same bytes Python froze")
    void javaSignsTheSameBytes() {
        var privateKey =
                EventSignature.privateKeyFromPkcs8(ContractFixtures.decodeBase64(CoreFixtures.privateKeyPkcs8Base64()));
        JsonNode envelope = CoreFixtures.instance("message_envelopes", "refund_requested");
        String resigned = CoreEventSignature.sign(envelope, privateKey);
        assertThat(resigned)
                .as("Ed25519 is deterministic, so a re-signature must reproduce the frozen one byte for byte")
                .isEqualTo(CoreFixtures.eventSignatures().get("refund_requested"));
    }

    @Test
    @DisplayName("the frozen signed member list is the core one, not the compat one")
    void theSignedMembersAreTheCoreOnes() {
        List<String> frozen = new ArrayList<>();
        CoreFixtures.expected()
                .get("signing_keys")
                .get("signed_members")
                .forEach(item -> frozen.add(item.stringValue()));
        assertThat(frozen).containsExactlyElementsOf(CoreEventSignature.SIGNABLE_KEYS);
        assertThat(frozen).contains("topic").doesNotContain("aggregate_id", "aggregate_version");
    }
}
