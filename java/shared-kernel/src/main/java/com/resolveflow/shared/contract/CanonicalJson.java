package com.resolveflow.shared.contract;

import java.math.BigInteger;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.util.ArrayList;
import java.util.List;
import tools.jackson.databind.JsonNode;
import tools.jackson.databind.ObjectMapper;

/**
 * RFC 8785 (JCS) canonical JSON and the execution payload hash.
 *
 * <p>docs/contracts.md:13 fixes request hashing over canonicalised JSON rather than raw bytes, and
 * docs/contracts.md:17 fixes exactly which fields the execution {@code payload_hash} covers. The
 * Python worker implements the same rules independently in {@code
 * resolveflow.contracts.canonical}; the two are compared against {@code
 * contracts/fixtures/expected-hashes.json} on every build. That agreement is the portability evidence
 * docs/contracts.md:17 asks for — one shared implementation would not have been evidence at all.
 *
 * <p>Three details are load-bearing and easy to get subtly wrong:
 *
 * <ul>
 *   <li>Object keys sort by UTF-16 code unit, not by code point. Java's {@link String#compareTo}
 *       already does that, which is why this class does not "fix" the ordering. A comparator written
 *       against code points would disagree with Python for supplementary characters, and the
 *       {@code utf16-key-ordering} fixture exists to catch exactly that.
 *   <li>Only JSON-required escaping is emitted: the five short forms, {@code \\u00xx} for other
 *       control characters, and nothing else. Escaping a non-ASCII character would still parse to
 *       the same value but would produce different bytes, and the hash is over bytes.
 *   <li>Numbers here are integers only. The domain forbids float money (docs/contracts.md:19 caps
 *       amounts at 1,000,000,000 minor units and revisions at 2^53-1), so a non-integer is refused
 *       instead of serialised. That closes the Java/Python/JavaScript number question rather than
 *       leaving it to hope.
 * </ul>
 */
public final class CanonicalJson {

    /** Fields covered by the REFUND execution payload_hash, per docs/contracts.md:17. */
    public static final List<String> REFUND_FIELDS = List.of(
            "operation_id",
            "case_id",
            "authorization_id",
            "input_revision",
            "line_id",
            "merchant_id",
            "action",
            "quantity",
            "currency",
            "amount_minor",
            "policy_version",
            "target_service");

    /** Fields covered by the RESHIP execution payload_hash. */
    public static final List<String> RESHIP_FIELDS = List.of(
            "operation_id",
            "case_id",
            "authorization_id",
            "input_revision",
            "line_id",
            "merchant_id",
            "action",
            "quantity",
            "currency",
            "address_hash",
            "policy_version",
            "target_service");

    private static final ObjectMapper MAPPER = new ObjectMapper();
    private static final char[] HEX = "0123456789abcdef".toCharArray();

    private CanonicalJson() {}

    /** Raised when a value has no RFC 8785 representation in this constrained subset. */
    public static class CanonicalizationException extends IllegalArgumentException {

        private static final long serialVersionUID = 1L;

        public CanonicalizationException(String message) {
            super(message);
        }
    }

    /** Return the RFC 8785 canonical JSON text for {@code value}. */
    public static String canonicalize(JsonNode value) {
        StringBuilder out = new StringBuilder();
        append(out, value);
        return out.toString();
    }

    /** Return the canonical bytes: what the digest is actually taken over. */
    public static byte[] canonicalBytes(JsonNode value) {
        return canonicalize(value).getBytes(StandardCharsets.UTF_8);
    }

    /** The hashed field set for an action; an unknown action is refused. */
    public static List<String> fieldsForAction(String action) {
        if ("REFUND".equals(action)) {
            return REFUND_FIELDS;
        }
        if ("RESHIP".equals(action)) {
            return RESHIP_FIELDS;
        }
        throw new CanonicalizationException("unknown action for payload hash: " + action);
    }

    /**
     * SHA-256 over the canonicalised execution payload field set.
     *
     * <p>{@code payload_hash} and {@code entitlement_id} are dropped if present, so the hash of a
     * fully built command matches the hash computed before entitlement reservation.
     */
    public static String payloadHash(JsonNode command) {
        if (command == null || !command.isObject()) {
            throw new CanonicalizationException("an execution command must be a JSON object");
        }
        JsonNode actionNode = command.get("action");
        if (actionNode == null || !actionNode.isString()) {
            throw new CanonicalizationException("an execution command must name a string action");
        }
        List<String> fields = fieldsForAction(actionNode.stringValue());

        List<String> missing = new ArrayList<>();
        for (String field : fields) {
            if (command.get(field) == null) {
                missing.add(field);
            }
        }
        if (!missing.isEmpty()) {
            throw new CanonicalizationException(
                    "missing field(s) for " + actionNode.stringValue() + " payload hash: " + missing);
        }

        var subset = MAPPER.createObjectNode();
        for (String field : fields) {
            subset.set(field, command.get(field));
        }
        return sha256Hex(canonicalBytes(subset));
    }

    /** SHA-256 over canonical bytes, for evidence and policy content hashes. */
    public static String contentHash(JsonNode value) {
        return sha256Hex(canonicalBytes(value));
    }

    /** Lowercase hex SHA-256, matching the {@code Sha256Hex} pattern in the contracts. */
    public static String sha256Hex(byte[] bytes) {
        byte[] digest;
        try {
            digest = MessageDigest.getInstance("SHA-256").digest(bytes);
        } catch (NoSuchAlgorithmException error) {
            throw new IllegalStateException("SHA-256 is required by the platform", error);
        }
        char[] text = new char[digest.length * 2];
        for (int i = 0; i < digest.length; i++) {
            int value = digest[i] & 0xff;
            text[i * 2] = HEX[value >>> 4];
            text[i * 2 + 1] = HEX[value & 0x0f];
        }
        return new String(text);
    }

    private static void append(StringBuilder out, JsonNode value) {
        if (value == null || value.isMissingNode()) {
            throw new CanonicalizationException("cannot canonicalise a missing node");
        }
        if (value.isNull()) {
            out.append("null");
            return;
        }
        if (value.isBoolean()) {
            out.append(value.asBoolean() ? "true" : "false");
            return;
        }
        if (value.isString()) {
            out.append('"');
            appendEscaped(out, value.stringValue());
            out.append('"');
            return;
        }
        if (value.isIntegralNumber()) {
            out.append(integerText(value));
            return;
        }
        if (value.isNumber()) {
            throw new CanonicalizationException(
                    "floating point is not canonicalisable in this domain; use integer minor units");
        }
        if (value.isArray()) {
            out.append('[');
            boolean first = true;
            for (JsonNode item : value) {
                if (!first) {
                    out.append(',');
                }
                first = false;
                append(out, item);
            }
            out.append(']');
            return;
        }
        if (value.isObject()) {
            // Keys sort by UTF-16 code unit: String.compareTo compares the char
            // values numerically, which is exactly the specified order.
            List<String> keys = new ArrayList<>(value.propertyNames());
            keys.sort(String::compareTo);
            out.append('{');
            for (int i = 0; i < keys.size(); i++) {
                if (i > 0) {
                    out.append(',');
                }
                String key = keys.get(i);
                out.append('"');
                appendEscaped(out, key);
                out.append("\":");
                append(out, value.get(key));
            }
            out.append('}');
            return;
        }
        throw new CanonicalizationException("unsupported node type: " + value.getNodeType());
    }

    private static String integerText(JsonNode value) {
        BigInteger number = value.bigIntegerValue();
        // JCS bounds numbers at 2^53-1 so that every language's double can hold them
        // exactly. Anything larger must be refused rather than truncated.
        if (number.abs().compareTo(BigInteger.valueOf(9007199254740991L)) > 0) {
            throw new CanonicalizationException("integer " + number + " exceeds the 2^53-1 contract bound");
        }
        return number.toString();
    }

    private static void appendEscaped(StringBuilder out, String text) {
        for (int i = 0; i < text.length(); i++) {
            char character = text.charAt(i);
            switch (character) {
                case '"' -> out.append("\\\"");
                case '\\' -> out.append("\\\\");
                case '\b' -> out.append("\\b");
                case '\f' -> out.append("\\f");
                case '\n' -> out.append("\\n");
                case '\r' -> out.append("\\r");
                case '\t' -> out.append("\\t");
                default -> {
                    if (character < 0x20) {
                        out.append("\\u");
                        out.append(HEX[(character >>> 12) & 0x0f]);
                        out.append(HEX[(character >>> 8) & 0x0f]);
                        out.append(HEX[(character >>> 4) & 0x0f]);
                        out.append(HEX[character & 0x0f]);
                    } else {
                        out.append(character);
                    }
                }
            }
        }
    }
}
