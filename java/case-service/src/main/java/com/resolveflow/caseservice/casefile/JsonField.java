package com.resolveflow.caseservice.casefile;

import tools.jackson.databind.JsonNode;
import tools.jackson.databind.ObjectMapper;

/**
 * A tolerant reader for one string member of a stored canonical-JSON detail.
 *
 * <p>Tolerant on purpose: a summary is a convenience, and a trajectory that refuses to load because one
 * row's detail was written by an older version would be worse than one row with a plainer sentence. A
 * missing or malformed member returns null, and the caller decides what to say instead.
 */
final class JsonField {

    private static final ObjectMapper MAPPER = new ObjectMapper();

    private JsonField() {}

    static String of(String canonicalJson, String field) {
        if (canonicalJson == null || canonicalJson.isBlank()) {
            return null;
        }
        try {
            JsonNode node = MAPPER.readTree(canonicalJson).get(field);
            return node == null || node.isNull() ? null : node.stringValue();
        } catch (RuntimeException error) {
            return null;
        }
    }

    /**
     * The same tolerance for a boolean member.
     *
     * <p>A separate reader rather than {@link #of} reading {@code "true"}: {@code stringValue()} on a boolean
     * node does not produce a string, so a flag read through the string reader looks absent — which is how a
     * retryable failure once said "handed to a person". {@code null} means absent or unreadable, and only the
     * caller decides what a missing flag means.
     */
    static Boolean flag(String canonicalJson, String field) {
        if (canonicalJson == null || canonicalJson.isBlank()) {
            return null;
        }
        try {
            JsonNode node = MAPPER.readTree(canonicalJson).get(field);
            return node == null || node.isNull() ? null : node.asBoolean();
        } catch (RuntimeException error) {
            return null;
        }
    }

    /**
     * The same tolerance for a whole-number member.
     *
     * <p>Needed for the same reason as {@link #flag}: an amount stored as a JSON number is not a string, so
     * reading it through {@link #of} reports it as absent. That is how a trajectory once said "方案已就绪"
     * for a proposal whose recomputed amount was right there in the row.
     */
    static Long number(String canonicalJson, String field) {
        if (canonicalJson == null || canonicalJson.isBlank()) {
            return null;
        }
        try {
            JsonNode node = MAPPER.readTree(canonicalJson).get(field);
            return node == null || node.isNull() ? null : node.asLong();
        } catch (RuntimeException error) {
            return null;
        }
    }
}
