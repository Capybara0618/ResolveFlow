package com.resolveflow.shared.contract;

import java.io.IOException;
import java.io.UncheckedIOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.Base64;
import java.util.LinkedHashMap;
import java.util.Map;
import tools.jackson.databind.JsonNode;
import tools.jackson.databind.ObjectMapper;
import tools.jackson.databind.node.ObjectNode;
import tools.jackson.databind.node.StringNode;

/**
 * Access to the T02 fixture corpus, so Java reads the same bytes Python reads.
 *
 * <p>This mirrors {@code resolveflow.contracts.fixtures}: entries point at each other with {@code
 * _ref} members and leave hash and signature values as {@code PLACEHOLDER_*} tokens, and this class
 * turns that into concrete instances. Both languages must consume the same corpus — two hand-copied
 * corpora would prove nothing about portability, and they would drift the first time one side was
 * edited.
 *
 * <p>The resolver is deliberately strict. A dangling {@code _ref} or an unresolved placeholder throws
 * instead of being skipped: a fixture that silently loses its payload would still "pass" and would
 * stop being evidence.
 */
public final class ContractFixtures {

    public static final String CANONICAL_CORPUS = "contracts/fixtures/examples/cross-language-canonical-inputs.json";
    public static final String VALID_CORPUS = "contracts/fixtures/examples/valid.json";
    public static final String REJECT_CORPUS = "contracts/fixtures/reject/reject.json";
    public static final String EXPECTED_HASHES = "contracts/fixtures/expected-hashes.json";
    public static final String EXPECTED_ENUMS = "contracts/fixtures/expected-enums.json";

    /** Marker file used to locate the repository root from any module's working directory. */
    private static final String ROOT_MARKER = EXPECTED_HASHES;

    private static final String PLACEHOLDER_PREFIX = "PLACEHOLDER_";
    private static final int MAX_PARENT_HOPS = 8;

    private static final ObjectMapper MAPPER = new ObjectMapper();

    private ContractFixtures() {}

    /** Raised when the corpus or the frozen expectations are not usable as written. */
    public static class FixtureException extends IllegalStateException {

        private static final long serialVersionUID = 1L;

        public FixtureException(String message) {
            super(message);
        }
    }

    /**
     * Locate the repository root by walking up from the working directory.
     *
     * <p>Surefire runs with the module directory as its working directory, so the root is a few hops
     * up; a test run from the repository root finds it immediately. Failing loudly here is better than
     * a test that silently asserts against nothing.
     */
    public static Path repoRoot() {
        Path candidate = Path.of(System.getProperty("user.dir", ".")).toAbsolutePath();
        for (int hop = 0; hop <= MAX_PARENT_HOPS && candidate != null; hop++) {
            if (Files.isRegularFile(candidate.resolve(ROOT_MARKER))) {
                return candidate;
            }
            candidate = candidate.getParent();
        }
        throw new FixtureException(
                "could not locate the repository root (no " + ROOT_MARKER + " in any parent of "
                        + System.getProperty("user.dir") + ")");
    }

    /** Load one repository-relative JSON file. */
    public static JsonNode load(String relativePath) {
        Path path = repoRoot().resolve(relativePath);
        if (!Files.isRegularFile(path)) {
            throw new FixtureException("fixture file is missing: " + relativePath);
        }
        try {
            return MAPPER.readTree(Files.readString(path, StandardCharsets.UTF_8));
        } catch (IOException error) {
            throw new UncheckedIOException("could not read " + relativePath, error);
        }
    }

    public static JsonNode canonicalCorpus() {
        return load(CANONICAL_CORPUS);
    }

    public static JsonNode validCorpus() {
        return load(VALID_CORPUS);
    }

    public static JsonNode rejectCorpus() {
        return load(REJECT_CORPUS);
    }

    public static JsonNode expectedHashes() {
        return load(EXPECTED_HASHES);
    }

    public static JsonNode expectedEnums() {
        return load(EXPECTED_ENUMS);
    }

    /**
     * Resolve one {@code message_envelope} fixture and inline the payload it references.
     *
     * <p>The envelope's {@code payload_ref} points at an execution command or a result payload
     * elsewhere in the corpus, and the command's own {@code payload_hash} is a placeholder, so the
     * referenced entry is substituted before being attached. Both languages therefore sign the same
     * bytes: the envelope is never signed over a literal {@code PLACEHOLDER_*} token.
     */
    public static ObjectNode messageEnvelope(String name) {
        JsonNode corpus = validCorpus();
        JsonNode section = corpus.get("message_envelope");
        JsonNode entry = section == null ? null : section.get(name);
        if (entry == null) {
            throw new FixtureException("no message_envelope fixture named '" + name + "'");
        }
        JsonNode referenceNode = entry.get("payload_ref");
        if (referenceNode == null || !referenceNode.isString()) {
            throw new FixtureException("envelope " + name + " has no payload_ref");
        }
        String reference = referenceNode.stringValue();
        if (!reference.startsWith("execution_command.") && !reference.startsWith("event_payload.")) {
            throw new FixtureException("envelope " + name + " references an unsupported section: " + reference);
        }
        ObjectNode instance = resolveInstance(entry, corpus);
        instance.set(
                "payload",
                substituteValues(resolveInstance(lookup(corpus, reference), corpus), placeholderValues()));
        return instance;
    }

    /** The frozen {@code PLACEHOLDER_*} table: hash and signature values a fixture refers to. */
    public static Map<String, String> placeholderValues() {
        Map<String, String> values = new LinkedHashMap<>();
        JsonNode table = expectedHashes().get("placeholder_values");
        if (table == null || !table.isObject()) {
            throw new FixtureException("expected-hashes.json has no placeholder_values object");
        }
        table.properties().forEach(entry -> values.put(entry.getKey(), entry.getValue().stringValue()));
        return values;
    }

    /**
     * Inline {@code _ref} members and drop {@code _}-prefixed annotations.
     *
     * <p>Every schema in this project is {@code additionalProperties: false}, so an annotation left in
     * the instance would make a valid fixture look invalid; it has to be removed rather than ignored.
     */
    public static ObjectNode resolveInstance(JsonNode section, JsonNode root) {
        if (section == null || !section.isObject()) {
            throw new FixtureException("a fixture section must be an object");
        }
        var resolved = MAPPER.createObjectNode();
        for (Map.Entry<String, JsonNode> member : section.properties()) {
            String key = member.getKey();
            JsonNode value = member.getValue();
            if (key.startsWith("_")) {
                continue;
            }
            if ("payload_ref".equals(key)) {
                if (!value.isString()) {
                    throw new FixtureException("payload_ref must be a string");
                }
                resolved.set("payload", lookup(root, value.stringValue()).deepCopy());
                continue;
            }
            JsonNode reference = value.isObject() ? value.get("_ref") : null;
            if (reference != null) {
                if (!reference.isString()) {
                    throw new FixtureException("_ref must be a string");
                }
                resolved.set(key, lookup(root, reference.stringValue()).deepCopy());
                continue;
            }
            resolved.set(key, value.deepCopy());
        }
        return resolved;
    }

    /** Resolve a dotted reference such as {@code execution_command.refund} inside the corpus root. */
    public static JsonNode lookup(JsonNode root, String dotted) {
        JsonNode node = root;
        for (String part : dotted.split("\\.")) {
            node = node == null ? null : node.get(part);
            if (node == null) {
                throw new FixtureException("fixture reference '" + dotted + "' does not resolve");
            }
        }
        return node;
    }

    /**
     * Replace {@code PLACEHOLDER_*} tokens with frozen values.
     *
     * <p>Objects are visited member by member and arrays element by element. A placeholder with no
     * frozen value is an error: it means the corpus and the generator have drifted and a test would
     * otherwise assert against a literal token.
     */
    public static JsonNode substituteValues(JsonNode instance, Map<String, String> values) {
        if (instance == null) {
            throw new FixtureException("cannot substitute values in a missing node");
        }
        if (instance.isString()) {
            String text = instance.stringValue();
            if (text.startsWith(PLACEHOLDER_PREFIX)) {
                String frozen = values.get(text);
                if (frozen == null) {
                    throw new FixtureException("no frozen value for placeholder '" + text + "'");
                }
                return StringNode.valueOf(frozen);
            }
            return instance.deepCopy();
        }
        if (instance.isObject()) {
            var result = MAPPER.createObjectNode();
            for (Map.Entry<String, JsonNode> member : instance.properties()) {
                result.set(member.getKey(), substituteValues(member.getValue(), values));
            }
            return result;
        }
        if (instance.isArray()) {
            var result = MAPPER.createArrayNode();
            for (JsonNode item : instance) {
                result.add(substituteValues(item, values));
            }
            return result;
        }
        return instance.deepCopy();
    }

    /** Copy of an object without its {@code _}-prefixed annotations, as the generator hashes it. */
    public static JsonNode stripAnnotations(JsonNode entry) {
        if (entry == null || !entry.isObject()) {
            return entry;
        }
        var stripped = MAPPER.createObjectNode();
        for (Map.Entry<String, JsonNode> member : entry.properties()) {
            if (!member.getKey().startsWith("_")) {
                stripped.set(member.getKey(), member.getValue());
            }
        }
        return stripped;
    }

    /** Decode the base64 fields of the frozen signing-key block. */
    public static byte[] decodeBase64(String text) {
        try {
            return Base64.getDecoder().decode(text);
        } catch (IllegalArgumentException error) {
            throw new FixtureException("frozen key material is not valid base64");
        }
    }
}