package com.resolveflow.spike.contract;

import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.util.ArrayList;
import java.util.Comparator;
import java.util.HexFormat;
import java.util.List;
import java.util.Map;

/**
 * RFC 8785 (JCS) canonical JSON, Java side of the cross-language fixture.
 *
 * <p>Written independently of the Python implementation so that agreement between
 * the two is evidence, not a tautology. Both must reproduce
 * contracts/cross-language-hash-expected.json exactly.
 *
 * <p>Scope: strings, integers, booleans, null, arrays and objects. Floating point
 * is rejected — contracts.md:19 forbids float money and caps revisions at 2^53-1,
 * which closes the Java/Python/JavaScript number agreement question.
 */
public final class PayloadHash {

    private PayloadHash() {
    }

    /** Fields covered by the execution payload_hash, per docs/contracts.md:17. */
    public static final List<String> REFUND_FIELDS = List.of(
            "operation_id", "case_id", "authorization_id", "input_revision", "line_id",
            "merchant_id", "action", "quantity", "currency", "amount_minor",
            "policy_version", "target_service");

    public static final List<String> RESHIP_FIELDS = List.of(
            "operation_id", "case_id", "authorization_id", "input_revision", "line_id",
            "merchant_id", "action", "quantity", "currency", "address_hash",
            "policy_version", "target_service");

    public static class CanonicalizationException extends RuntimeException {
        public CanonicalizationException(String message) {
            super(message);
        }
    }

    public static String canonicalize(Object value) {
        StringBuilder out = new StringBuilder();
        write(value, out);
        return out.toString();
    }

    public static byte[] canonicalBytes(Object value) {
        return canonicalize(value).getBytes(StandardCharsets.UTF_8);
    }

    private static void write(Object value, StringBuilder out) {
        switch (value) {
            case null -> out.append("null");
            case Boolean b -> out.append(b ? "true" : "false");
            case String s -> writeString(s, out);
            case Integer i -> out.append(i.intValue());
            case Long l -> out.append(l.longValue());
            case Short s -> out.append(s.intValue());
            case Byte b -> out.append(b.intValue());
            case java.math.BigInteger bi -> out.append(bi.toString());
            case Double d -> throw new CanonicalizationException(
                    "floating point is not canonicalisable in this domain: " + d);
            case Float f -> throw new CanonicalizationException(
                    "floating point is not canonicalisable in this domain: " + f);
            case List<?> list -> {
                out.append('[');
                for (int i = 0; i < list.size(); i++) {
                    if (i > 0) {
                        out.append(',');
                    }
                    write(list.get(i), out);
                }
                out.append(']');
            }
            case Map<?, ?> map -> {
                List<String> keys = new ArrayList<>(map.size());
                for (Object key : map.keySet()) {
                    if (!(key instanceof String s)) {
                        throw new CanonicalizationException(
                                "object key must be a string, got " + key.getClass().getName());
                    }
                    keys.add(s);
                }
                // JCS orders keys by UTF-16 code unit, not code point.
                keys.sort(Comparator.comparing(PayloadHash::utf16SortKey, PayloadHash::compareBytes));
                out.append('{');
                for (int i = 0; i < keys.size(); i++) {
                    if (i > 0) {
                        out.append(',');
                    }
                    writeString(keys.get(i), out);
                    out.append(':');
                    write(map.get(keys.get(i)), out);
                }
                out.append('}');
            }
            default -> throw new CanonicalizationException(
                    "unsupported type: " + value.getClass().getName());
        }
    }

    private static byte[] utf16SortKey(String text) {
        return text.getBytes(StandardCharsets.UTF_16BE);
    }

    private static int compareBytes(byte[] a, byte[] b) {
        int limit = Math.min(a.length, b.length);
        for (int i = 0; i < limit; i++) {
            int cmp = (a[i] & 0xff) - (b[i] & 0xff);
            if (cmp != 0) {
                return cmp;
            }
        }
        return a.length - b.length;
    }

    private static void writeString(String s, StringBuilder out) {
        out.append('"');
        for (int i = 0; i < s.length(); i++) {
            char c = s.charAt(i);
            switch (c) {
                case '"' -> out.append("\\\"");
                case '\\' -> out.append("\\\\");
                case '\b' -> out.append("\\b");
                case '\f' -> out.append("\\f");
                case '\n' -> out.append("\\n");
                case '\r' -> out.append("\\r");
                case '\t' -> out.append("\\t");
                default -> {
                    if (c < 0x20) {
                        out.append(String.format("\\u%04x", (int) c));
                    } else {
                        // Raw UTF-8 for everything else, as JCS requires.
                        out.append(c);
                    }
                }
            }
        }
        out.append('"');
    }

    public static String payloadHash(Map<String, Object> payload) {
        Object action = payload.get("action");
        List<String> fields;
        if ("REFUND".equals(action)) {
            fields = REFUND_FIELDS;
        } else if ("RESHIP".equals(action)) {
            fields = RESHIP_FIELDS;
        } else {
            throw new CanonicalizationException("unknown action for payload hash: " + action);
        }
        // LinkedHashMap preserves field order; canonicalize() sorts keys anyway.
        Map<String, Object> subset = new java.util.LinkedHashMap<>();
        for (String name : fields) {
            if (!payload.containsKey(name)) {
                throw new CanonicalizationException(
                        "missing field for " + action + " payload hash: " + name);
            }
            subset.put(name, payload.get(name));
        }
        return sha256Hex(canonicalBytes(subset));
    }

    public static String contentHash(Object value) {
        return sha256Hex(canonicalBytes(value));
    }

    public static String sha256Hex(byte[] input) {
        try {
            return HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256").digest(input));
        } catch (NoSuchAlgorithmException e) {
            throw new IllegalStateException("SHA-256 unavailable", e);
        }
    }
}