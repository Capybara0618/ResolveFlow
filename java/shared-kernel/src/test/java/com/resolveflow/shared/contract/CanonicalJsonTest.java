package com.resolveflow.shared.contract;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import tools.jackson.databind.JsonNode;
import tools.jackson.databind.ObjectMapper;
import tools.jackson.databind.node.ObjectNode;

/**
 * Unit tests for the canonicalisation rules themselves.
 *
 * <p>{@link ContractCorpusAgreementTest} proves Java and Python agree on the frozen corpus; this class
 * proves the rules are implemented as documented for the cases a corpus cannot express as a list of
 * values — ordering, escaping, and what must be refused.
 */
class CanonicalJsonTest {

    private static final ObjectMapper MAPPER = new ObjectMapper();

    private static JsonNode json(String text) {
        return MAPPER.readTree(text);
    }

    @Test
    @DisplayName("Object keys sort by UTF-16 code unit, matching RFC 8785")
    void ordersKeysByUtf16CodeUnit() {
        // U+10000 is the surrogate pair D800 DC00, so under UTF-16 code-unit ordering it sorts
        // before both U+E000 and U+FFFD; a code-point sort would put the two BMP keys first.
        String canonical = CanonicalJson.canonicalize(
                json("{\"\uD800\uDC00\":\"supplementary\",\"\uFFFD\":\"replacement\",\"\uE000\":\"private-use\"}"));

        assertThat(canonical)
                .isEqualTo(
                        "{\"\uD800\uDC00\":\"supplementary\",\"\uE000\":\"private-use\",\"\uFFFD\":\"replacement\"}");
        // The ordering that actually distinguishes the two rules, asserted rather than implied.
        assertThat(canonical.indexOf("\uD800\uDC00")).isLessThan(canonical.indexOf("\uE000"));
        assertThat(canonical.indexOf("\uE000")).isLessThan(canonical.indexOf("\uFFFD"));
    }

    @Test
    @DisplayName("Sorting is by code unit, not by locale or case-insensitive order")
    void ordersAsciiByCodeUnit() {
        assertThat(CanonicalJson.canonicalize(json("{\"b\":1,\"A\":2,\"a\":3}")))
                .isEqualTo("{\"A\":2,\"a\":3,\"b\":1}");
    }

    @Test
    @DisplayName("Escapes only what JSON requires and leaves non-ASCII characters raw")
    void escapesMinimally() {
        assertThat(CanonicalJson.canonicalize(json("{\"t\":\"tab:\\t newline:\\n quote:\\\" backslash:\\\\\"}")))
                .isEqualTo("{\"t\":\"tab:\\t newline:\\n quote:\\\" backslash:\\\\\"}");
        // Control characters have no short form and use a four-digit escape with lowercase hex.
        assertThat(CanonicalJson.canonicalize(json("{\"c\":\"unit-sep:\\u001f\"}")))
                .isEqualTo("{\"c\":\"unit-sep:\\u001f\"}");
        // A non-ASCII character stays as itself: escaping it would parse identically but
        // produce different bytes, and the hash is over bytes.
        assertThat(CanonicalJson.canonicalize(json("{\"n\":\"\u5f20\u4e09\"}"))).isEqualTo("{\"n\":\"\u5f20\u4e09\"}");
    }

    @Test
    @DisplayName("null and booleans keep their JSON form instead of being dropped or numbered")
    void keepsNullsAndBooleans() {
        assertThat(CanonicalJson.canonicalize(json("{\"n\":null,\"t\":true,\"f\":false}")))
                .isEqualTo("{\"f\":false,\"n\":null,\"t\":true}");
    }

    @Test
    @DisplayName("Array order is preserved: it is data, not a set")
    void preservesArrayOrder() {
        assertThat(CanonicalJson.canonicalize(json("[3,1,2]"))).isEqualTo("[3,1,2]");
    }

    @Test
    @DisplayName("A float is refused rather than rounded, because money is integer minor units")
    void refusesFloatingPoint() {
        assertThatThrownBy(() -> CanonicalJson.canonicalize(json("{\"amount_minor\":200.5}")))
                .isInstanceOf(CanonicalJson.CanonicalizationException.class)
                .hasMessageContaining("floating point");
    }

    @Test
    @DisplayName("An integer beyond 2^53-1 is refused: Java, Python and JavaScript must agree exactly")
    void refusesIntegersBeyondTheExactRange() {
        assertThatThrownBy(() -> CanonicalJson.contentHash(json("{\"version\":9007199254740992}")))
                .isInstanceOf(CanonicalJson.CanonicalizationException.class)
                .hasMessageContaining("2^53-1");
        // The bound itself is legal.
        assertThat(CanonicalJson.canonicalize(json("{\"version\":9007199254740991}")))
                .isEqualTo("{\"version\":9007199254740991}");
    }

    @Test
    @DisplayName("The payload hash covers exactly the documented field set")
    void hashesTheDocumentedFieldSet() {
        var command = MAPPER.createObjectNode();
        command.put("operation_id", "3f2504e0-4f89-41d3-9a0c-0305e82c3301");
        command.put("case_id", "9c858901-8a57-4791-81fe-4c455b099bc9");
        command.put("authorization_id", "7d444840-9dc0-11d1-b245-5ffdce74fad2");
        command.put("input_revision", 1);
        command.put("line_id", "7001");
        command.put("merchant_id", "1");
        command.put("action", "REFUND");
        command.put("quantity", 1);
        command.put("currency", "CNY");
        command.put("amount_minor", 20000);
        command.put("policy_version", "policy-2026.09-refund-v3");
        command.put("target_service", "commerce-service");

        String beforeReservation = CanonicalJson.payloadHash(command);

        // Fields added after the hash is computed must not change it: entitlement_id is filled in
        // when the entitlement is reserved, and payload_hash is the hash itself.
        command.put("entitlement_id", "ent-7001-refund-1");
        command.put("payload_hash", beforeReservation);
        command.put("trace_id", "trace-abc");
        command.put("sent_at", "2026-09-18T00:00:00Z");

        assertThat(CanonicalJson.payloadHash(command)).isEqualTo(beforeReservation);
    }

    @Test
    @DisplayName("REFUND and RESHIP hash different field sets, so an amount never leaks into a reship")
    void refundAndReshipUseDifferentFieldSets() {
        assertThat(CanonicalJson.fieldsForAction("REFUND"))
                .contains("amount_minor")
                .doesNotContain("address_hash");
        assertThat(CanonicalJson.fieldsForAction("RESHIP"))
                .contains("address_hash")
                .doesNotContain("amount_minor");
        assertThatThrownBy(() -> CanonicalJson.fieldsForAction("PARTIAL_REFUND"))
                .isInstanceOf(CanonicalJson.CanonicalizationException.class);
    }

    @Test
    @DisplayName("A command missing a hashed field is refused: two different payloads must not hash alike")
    void refusesCommandsWithMissingHashedFields() {
        var command = MAPPER.createObjectNode();
        command.put("action", "REFUND");
        command.put("operation_id", "3f2504e0-4f89-41d3-9a0c-0305e82c3301");

        assertThatThrownBy(() -> CanonicalJson.payloadHash(command))
                .isInstanceOf(CanonicalJson.CanonicalizationException.class)
                .hasMessageContaining("missing field(s)");
    }

    @Test
    @DisplayName("Digests are lowercase hex SHA-256, as the Sha256Hex pattern requires")
    void producesLowercaseHexDigests() {
        String digest = CanonicalJson.sha256Hex("abc".getBytes(StandardCharsets.UTF_8));
        assertThat(digest).isEqualTo("ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad");
        assertThat(digest).matches("^[a-f0-9]{64}$");
    }

    @Test
    @DisplayName("The canonical text of a document is stable across a re-parse")
    void canonicalTextIsStable() {
        String text = CanonicalJson.canonicalize(
                ContractFixtures.canonicalCorpus().get("unicode_documents").get("control-and-supplementary"));
        String again = CanonicalJson.canonicalize(json(text));
        assertThat(again).isEqualTo(text);
    }

    @Test
    @DisplayName("Signing input normalises absent optional members to null")
    void normalisesAbsentOptionalMembers() {
        ObjectNode withNull = ContractFixtures.messageEnvelope("refund_requested_signed");
        ObjectNode without = ContractFixtures.messageEnvelope("refund_requested_signed");
        withNull.putNull("traceparent");
        without.remove("traceparent");

        assertThat(EventSignature.signingInputBytes(without)).isEqualTo(EventSignature.signingInputBytes(withNull));
    }

    @Test
    @DisplayName("The signature is excluded from its own signing input")
    void excludesTheSignatureFromItsOwnInput() {
        ObjectNode envelope = ContractFixtures.messageEnvelope("refund_requested_signed");
        String before = new String(EventSignature.signingInputBytes(envelope), StandardCharsets.UTF_8);

        ObjectNode tampered = envelope.deepCopy();
        tampered.put("signature", "some-other-signature");
        String after = new String(EventSignature.signingInputBytes(tampered), StandardCharsets.UTF_8);

        assertThat(after).isEqualTo(before);
        assertThat(EventSignature.SIGNABLE_KEYS).doesNotContain("signature");
        assertThat(EventSignature.SIGNABLE_KEYS).contains("signing_key_id");
    }

    @Test
    @DisplayName("A tampered payload fails verification even though the signature itself is intact")
    void refusesATamperedPayload() {
        ObjectNode envelope = ContractFixtures.messageEnvelope("refund_requested_signed");
        JsonNode keys = ContractFixtures.expectedHashes().get("signing_keys");
        var privateKey = EventSignature.privateKeyFromPkcs8(ContractFixtures.decodeBase64(
                keys.get("private_key_pkcs8_base64").stringValue()));
        var publicKey = EventSignature.publicKeyFromSpki(
                ContractFixtures.decodeBase64(keys.get("public_key_spki_base64").stringValue()));

        String signature = EventSignature.sign(envelope, privateKey);
        EventSignature.verify(envelope, signature, publicKey);

        ObjectNode tampered = envelope.deepCopy();
        tampered.get("payload").asObject().put("amount_minor", 999999);
        assertThatThrownBy(() -> EventSignature.verify(tampered, signature, publicKey))
                .isInstanceOf(EventSignature.EventSignatureException.class)
                .hasMessageContaining("does not cover");
    }

    @Test
    @DisplayName("Wire enums match the frozen mapping, and a renamed constant cannot change the wire value")
    void enumsMatchTheFrozenMapping() {
        JsonNode frozen = ContractFixtures.expectedEnums().get("enums");
        Map<String, List<String>> expected = new LinkedHashMap<>();
        for (Map.Entry<String, JsonNode> group : frozen.properties()) {
            List<String> wireValues = new ArrayList<>();
            group.getValue().forEach(member -> wireValues.add(member.stringValue()));
            expected.put(group.getKey(), wireValues);
        }

        // The frozen file is the specification; wireValues() is the Java implementation.
        assertThat(ContractEnums.wireValues()).isEqualTo(expected);
        assertThat(ContractEnums.EventType.REFUND_REQUESTED.wire()).isEqualTo("RefundRequested");
        assertThat(ContractEnums.Producer.COMMERCE.wire()).isEqualTo("commerce-service");
        // A renamed Java constant must not move the wire value.
        assertThat(ContractEnums.OperationState.TARGET_SUCCEEDED.wire()).isEqualTo("TARGET_SUCCEEDED");
    }
}
