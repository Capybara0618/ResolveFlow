package com.resolveflow.spike;

import com.resolveflow.spike.contract.PayloadHash;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import tools.jackson.core.type.TypeReference;
import tools.jackson.databind.ObjectMapper;

import java.io.File;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.util.List;
import java.util.Map;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

/**
 * T00 gate: Java and Python must canonicalise the same payload to the same bytes.
 *
 * <p>Reads the shared fixture under spikes/compatibility/contracts and compares
 * against values frozen from the Python implementation. This is the check
 * docs/contracts.md:13 requires before request hashing is treated as portable.
 * Also exercises Jackson 3 (the Boot 4 default), which stack-and-sources.md asks
 * to be verified.
 */
class CrossLanguageHashIT {

    static final File CONTRACTS = new File("../../contracts");
    static final ObjectMapper MAPPER = new ObjectMapper();

    @Test
    @DisplayName("Java reproduces every frozen Python hash byte-for-byte")
    void javaMatchesPythonHashes() throws Exception {
        Map<String, Object> inputs = MAPPER.readValue(
                new File(CONTRACTS, "cross-language-hash-inputs.json"),
                new TypeReference<Map<String, Object>>() {
                });
        Map<String, Object> expected = MAPPER.readValue(
                new File(CONTRACTS, "cross-language-hash-expected.json"),
                new TypeReference<Map<String, Object>>() {
                });

        @SuppressWarnings("unchecked")
        Map<String, String> expectedPayloadHashes =
                (Map<String, String>) expected.get("execution_payload_hashes");
        @SuppressWarnings("unchecked")
        Map<String, String> expectedContentHashes =
                (Map<String, String>) expected.get("content_hashes");

        @SuppressWarnings("unchecked")
        List<Map<String, Object>> payloads = (List<Map<String, Object>>) inputs.get("execution_payloads");
        assertThat(payloads).isNotEmpty();
        for (Map<String, Object> item : payloads) {
            String name = (String) item.get("name");
            @SuppressWarnings("unchecked")
            Map<String, Object> payload = (Map<String, Object>) item.get("payload");
            assertThat(PayloadHash.payloadHash(payload))
                    .as("payload_hash for %s must match the Python-computed value", name)
                    .isEqualTo(expectedPayloadHashes.get(name));
        }

        @SuppressWarnings("unchecked")
        List<Map<String, Object>> contents = (List<Map<String, Object>>) inputs.get("content_hashes");
        for (Map<String, Object> item : contents) {
            String name = (String) item.get("name");
            assertThat(PayloadHash.contentHash(item.get("value")))
                    .as("content hash for %s must match the Python-computed value", name)
                    .isEqualTo(expectedContentHashes.get(name));
        }
    }

    @Test
    @DisplayName("JCS key ordering follows UTF-16 code units, not code points")
    void utf16KeyOrdering() {
        // U+10000 (surrogate pair D800 DC00) sorts before U+FFFD in UTF-16 order,
        // but after it in code-point order. A naive sort produces different bytes.
        String canonical = PayloadHash.canonicalize(new java.util.LinkedHashMap<>(Map.of(
                "b", "ascii",
                "A", "upper",
                "�", "replacement-char",
                "𐀀", "supplementary-plane-char")));

        int asciiUpper = canonical.indexOf("\"A\"");
        int asciiLower = canonical.indexOf("\"b\"");
        int supplementary = canonical.indexOf("\"\\ud800\\udc00\"") >= 0
                ? canonical.indexOf("\"\\ud800\\udc00\"")
                : canonical.indexOf("𐀀");
        int replacement = canonical.indexOf("�");

        assertThat(asciiUpper).isLessThan(asciiLower);
        assertThat(asciiLower).isLessThan(supplementary);
        assertThat(supplementary)
                .as("supplementary char must sort before U+FFFD in UTF-16 order")
                .isLessThan(replacement);
    }

    @Test
    @DisplayName("Float money is refused rather than canonicalised")
    void floatMoneyIsRejected() {
        assertThatThrownBy(() -> PayloadHash.canonicalize(Map.of("amount_minor", 200.5)))
                .isInstanceOf(PayloadHash.CanonicalizationException.class);
    }

    @Test
    @DisplayName("A payload missing a hashed field is refused")
    void missingFieldIsRejected() {
        Map<String, Object> incomplete = new java.util.LinkedHashMap<>();
        incomplete.put("action", "REFUND");
        incomplete.put("operation_id", "3f2504e0-4f89-41d3-9a0c-0305e82c3301");
        assertThatThrownBy(() -> PayloadHash.payloadHash(incomplete))
                .isInstanceOf(PayloadHash.CanonicalizationException.class)
                .hasMessageContaining("missing field");
    }

    @Test
    @DisplayName("entitlement_id and payload_hash do not affect the hash")
    void excludedFieldsDoNotChangeHash() throws Exception {
        @SuppressWarnings("unchecked")
        Map<String, Object> inputs = MAPPER.readValue(
                new File(CONTRACTS, "cross-language-hash-inputs.json"),
                new TypeReference<Map<String, Object>>() {
                });
        @SuppressWarnings("unchecked")
        List<Map<String, Object>> payloads = (List<Map<String, Object>>) inputs.get("execution_payloads");
        @SuppressWarnings("unchecked")
        Map<String, Object> payload = (Map<String, Object>) payloads.get(0).get("payload");

        String before = PayloadHash.payloadHash(payload);

        // Fields filled in after the hash is computed must not change it.
        Map<String, Object> withRuntimeFields = new java.util.LinkedHashMap<>(payload);
        withRuntimeFields.put("entitlement_id", "ent-1");
        withRuntimeFields.put("payload_hash", before);
        withRuntimeFields.put("trace_id", "trace-abc");
        assertThat(PayloadHash.payloadHash(withRuntimeFields)).isEqualTo(before);
    }

    @Test
    @DisplayName("Canonical output is stable across runs and free of whitespace")
    void canonicalOutputIsStable() throws Exception {
        // Arrays.asList, not List.of: List.of rejects null elements, and null must
        // still be canonicalised to the JSON literal null.
        var mixed = java.util.Arrays.asList(1, true, null, "x");
        String canonical = PayloadHash.canonicalize(Map.of("b", 1, "a", mixed));
        assertThat(canonical).isEqualTo("{\"a\":[1,true,null,\"x\"],\"b\":1}");
        assertThat(canonical).doesNotContain(" ");
        assertThat(PayloadHash.canonicalize(Map.of("b", 1, "a", mixed))).isEqualTo(canonical);

        // Fixture files are UTF-8; read them the same way the other language writes them.
        String raw = Files.readString(
                new File(CONTRACTS, "cross-language-hash-expected.json").toPath(),
                StandardCharsets.UTF_8);
        assertThat(raw).contains("cross-language-hash-inputs.json");
    }
}