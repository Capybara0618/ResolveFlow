package com.resolveflow.shared.core;

import com.resolveflow.shared.contract.ContractFixtures;
import java.util.LinkedHashMap;
import java.util.Map;
import tools.jackson.databind.JsonNode;
import tools.jackson.databind.ObjectMapper;
import tools.jackson.databind.node.ObjectNode;

/**
 * Access to the core-v1.2 fixture corpus.
 *
 * <p>Java and Python read the same bytes: {@code contracts/core/fixtures/valid.json} holds the
 * positive instances and {@code expected.json} the frozen values the two languages must agree on.
 * Two hand-copied corpora would prove nothing about portability and would drift the first time one
 * side was edited.
 *
 * <p>The resolver is strict for the same reason the compat one is: a dangling reference or an
 * unresolved placeholder throws instead of being skipped, because a fixture that silently loses its
 * payload would still "pass" and would stop being evidence.
 */
public final class CoreFixtures {

    public static final String VALID_CORPUS = "contracts/core/fixtures/valid.json";
    public static final String REJECT_CORPUS = "contracts/core/fixtures/reject.json";
    public static final String EXPECTED = "contracts/core/fixtures/expected.json";

    /** Section name -> the schema URN its fixtures are validated against. */
    public static final Map<String, String> SCHEMA_OF_SECTION = Map.of(
            "execution_commands", "urn:resolveflow:core:refund-command:v2",
            "message_envelopes", "urn:resolveflow:core:event-envelope:v2",
            "agent_proposals", "urn:resolveflow:core:agent-proposal:v2");

    private static final String PLACEHOLDER_PREFIX = "PLACEHOLDER_";

    private static final ObjectMapper MAPPER = new ObjectMapper();

    private CoreFixtures() {}

    public static JsonNode validCorpus() {
        return ContractFixtures.load(VALID_CORPUS);
    }

    public static JsonNode rejectCorpus() {
        return ContractFixtures.load(REJECT_CORPUS);
    }

    public static JsonNode expected() {
        return ContractFixtures.load(EXPECTED);
    }

    /** The frozen {@code PLACEHOLDER_*} table: core payload hashes and event signatures. */
    public static Map<String, String> placeholderValues() {
        return stringMap(expected().get("placeholder_values"), "placeholder_values");
    }

    /** The frozen payload hash of every command component, keyed by component name. */
    public static Map<String, String> payloadHashes() {
        return stringMap(expected().get("payload_hashes"), "payload_hashes");
    }

    /** The canonical JSON each payload hash covers, keyed by component name. */
    public static Map<String, String> canonicalPayloads() {
        return stringMap(expected().get("canonical_payloads"), "canonical_payloads");
    }

    /** The frozen signature of every envelope, keyed by envelope name. */
    public static Map<String, String> eventSignatures() {
        return stringMap(expected().get("event_signatures"), "event_signatures");
    }

    /** The exact bytes each signature covers, keyed by envelope name. */
    public static Map<String, String> signingInputs() {
        return stringMap(expected().get("signing_inputs"), "signing_inputs");
    }

    /** The core signing key as a PKCS#8 DER blob, base64. */
    public static String privateKeyPkcs8Base64() {
        return expected().get("signing_keys").get("private_key_pkcs8_base64").stringValue();
    }

    /** The matching public key as an SPKI DER blob, base64. */
    public static String publicKeySpkiBase64() {
        return expected().get("signing_keys").get("public_key_spki_base64").stringValue();
    }

    /** Every fixture name in one section, annotations excluded. */
    public static java.util.List<String> names(String section) {
        JsonNode node = validCorpus().get(section);
        if (node == null || !node.isObject()) {
            throw new ContractFixtures.FixtureException("no core corpus section '" + section + "'");
        }
        return node.properties().stream()
                .map(Map.Entry::getKey)
                .filter(name -> !name.startsWith("_"))
                .sorted()
                .toList();
    }

    /**
     * One concrete positive instance: references inlined, annotations dropped, placeholders filled.
     *
     * <p>{@code payload_ref} (the compat convention) and a whole-body {@code _ref} alias are both
     * resolved. The alias case matters: the compat resolver drops every {@code _}-prefixed key as an
     * annotation, so a top-level alias would silently become an empty fixture — a fixture that
     * validates nothing.
     */
    public static ObjectNode instance(String section, String name) {
        JsonNode corpus = validCorpus();
        JsonNode entry =
                corpus.get(section) == null ? null : corpus.get(section).get(name);
        if (entry == null) {
            throw new ContractFixtures.FixtureException("no core fixture " + section + "." + name);
        }
        JsonNode resolved = entry.isObject() && entry.get("_ref") != null
                ? resolveReference(corpus, entry, section + "." + name)
                : resolveObject(corpus, entry, section + "." + name);
        return (ObjectNode) ContractFixtures.substituteValues(resolved, placeholderValues());
    }

    /** Inline a whole-body {@code _ref} alias or a nested one, then resolve the object normally. */
    private static JsonNode resolveReference(JsonNode root, JsonNode entry, String where) {
        JsonNode reference = entry.get("_ref");
        if (!reference.isString()) {
            throw new ContractFixtures.FixtureException("core fixture " + where + " has a non-string _ref");
        }
        var extra = MAPPER.createObjectNode();
        entry.properties().forEach(member -> {
            if (!member.getKey().startsWith("_")) {
                extra.set(member.getKey(), member.getValue());
            }
        });
        if (!extra.isEmpty()) {
            throw new ContractFixtures.FixtureException(
                    "core fixture " + where + " aliases " + reference.stringValue() + " and cannot also set members");
        }
        ObjectNode target = (ObjectNode)
                ContractFixtures.lookup(root, reference.stringValue()).deepCopy();
        return resolveObject(root, target, where);
    }

    private static JsonNode resolveObject(JsonNode root, JsonNode entry, String where) {
        if (entry == null || !entry.isObject()) {
            throw new ContractFixtures.FixtureException("core fixture " + where + " must be an object");
        }
        var resolved = MAPPER.createObjectNode();
        entry.properties().forEach(member -> {
            String key = member.getKey();
            JsonNode value = member.getValue();
            if (strip(key)) {
                return;
            }
            if ("payload_ref".equals(key)) {
                if (!value.isString()) {
                    throw new ContractFixtures.FixtureException(where + ".payload_ref must be a string");
                }
                resolved.set(
                        "payload",
                        ContractFixtures.stripAnnotations(ContractFixtures.lookup(root, value.stringValue())));
                return;
            }
            JsonNode inline = value.isObject() ? value.get("_ref") : null;
            if (inline != null) {
                if (!inline.isString()) {
                    throw new ContractFixtures.FixtureException(where + "." + key + "._ref must be a string");
                }
                resolved.set(
                        key, ContractFixtures.stripAnnotations(ContractFixtures.lookup(root, inline.stringValue())));
                return;
            }
            resolved.set(key, stripAnnotationsDeep(value));
        });
        return resolved;
    }

    /**
     * Remove {@code _}-prefixed annotations at every depth.
     *
     * <p>The compat helper only strips the top level, which is not enough here: an annotation inside a
     * referenced component would travel into the instance, and every core schema is {@code
     * additionalProperties: false}, so the instance would be rejected for carrying documentation.
     */
    private static JsonNode stripAnnotationsDeep(JsonNode node) {
        if (node.isObject()) {
            var result = MAPPER.createObjectNode();
            node.properties().forEach(member -> {
                if (!strip(member.getKey())) {
                    result.set(member.getKey(), stripAnnotationsDeep(member.getValue()));
                }
            });
            return result;
        }
        if (node.isArray()) {
            var result = MAPPER.createArrayNode();
            node.forEach(item -> result.add(stripAnnotationsDeep(item)));
            return result;
        }
        return node.deepCopy();
    }

    private static boolean strip(String key) {
        return key.startsWith("_");
    }

    private static Map<String, String> stringMap(JsonNode node, String what) {
        if (node == null || !node.isObject()) {
            throw new ContractFixtures.FixtureException("expected.json has no " + what + " object");
        }
        Map<String, String> values = new LinkedHashMap<>();
        node.properties()
                .forEach(entry -> values.put(entry.getKey(), entry.getValue().stringValue()));
        return values;
    }

    /** True when a value is an unresolved placeholder, which must never reach a test. */
    public static boolean isPlaceholder(JsonNode node) {
        return node != null && node.isString() && node.stringValue().startsWith(PLACEHOLDER_PREFIX);
    }
}
