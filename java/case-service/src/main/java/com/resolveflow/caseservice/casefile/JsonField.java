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
}
