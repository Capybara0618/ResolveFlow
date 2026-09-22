package com.resolveflow.commerce.refund;

import com.resolveflow.shared.contract.CanonicalJson;
import java.util.List;
import tools.jackson.databind.JsonNode;
import tools.jackson.databind.ObjectMapper;
import tools.jackson.databind.node.ObjectNode;

/**
 * The twelve fields a refund command is, read from the document Case sent
 * (contracts/core/refund-command.schema.json).
 *
 * <p>Commerce does not trust the document's members to be {the right number, the right kind}: the shape is
 * checked here, and the payload hash is **re-derived** from the members rather than compared to itself
 * (docs/contracts.md:130 — the consumer must still verify the hash). A command whose {@code payload_hash}
 * does not match its own contents is refused, because the hash is what the authorisation fixed
 * (docs/core-contracts.md:19) and a mismatch means the authorisation and the command are about different
 * payments.
 *
 * <p>{@code target_service} is a constant in core-v1.2: there is exactly one executor
 * (docs/core-contracts.md:65), so a command addressed elsewhere is not a command this service can execute
 * even if every other member is well-formed.
 */
public record RefundCommand(
        String operationId,
        String caseId,
        String authorizationId,
        long inputRevision,
        String lineId,
        String merchantId,
        String action,
        int quantity,
        String currency,
        long amountMinor,
        String payloadHash,
        String policyVersion) {

    /** The one action and the one addressee this protocol has (docs/core-contracts.md:65). */
    public static final String ACTION_REFUND = "REFUND";

    public static final String TARGET_SERVICE = "commerce-service";

    /** Exactly the members the schema requires: no more, and none of them optional. */
    private static final List<String> REQUIRED_MEMBERS = List.of(
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
            "payload_hash",
            "policy_version",
            "target_service");

    private static final int MAX_QUANTITY = 1000;

    private static final long MAX_AMOUNT_MINOR = 1_000_000_000L;

    /** Parse and validate a command document. A refusal here is a fault in the message, not in the world. */
    public static RefundCommand parse(ObjectMapper mapper, JsonNode document) {
        if (document == null || !document.isObject()) {
            throw new RefundRejectedException(RefundError.MALFORMED_COMMAND, "a refund command is a JSON object");
        }
        for (String member : REQUIRED_MEMBERS) {
            if (!document.has(member)) {
                throw new RefundRejectedException(RefundError.MALFORMED_COMMAND, "refund command is missing " + member);
            }
        }
        if (document.properties().size() != REQUIRED_MEMBERS.size()) {
            // The schema says additionalProperties:false. Accepting an unknown member would mean two
            // different documents could describe the same payment, and the payload hash could not tell
            // them apart because it only covers the twelve.
            throw new RefundRejectedException(
                    RefundError.MALFORMED_COMMAND, "refund command carries members the protocol does not define");
        }
        for (String member : REQUIRED_MEMBERS) {
            if (!document.get(member).isValueNode()) {
                throw new RefundRejectedException(
                        RefundError.MALFORMED_COMMAND, member + " must be a scalar, not a structure");
            }
        }

        RefundCommand command = new RefundCommand(
                requiredText(document, "operation_id"),
                requiredText(document, "case_id"),
                requiredText(document, "authorization_id"),
                requiredPositive(document, "input_revision"),
                requiredText(document, "line_id"),
                requiredText(document, "merchant_id"),
                requiredText(document, "action"),
                (int) requiredPositive(document, "quantity"),
                requiredText(document, "currency"),
                requiredPositive(document, "amount_minor"),
                requiredText(document, "payload_hash"),
                requiredText(document, "policy_version"));
        command.validate(mapper, requiredText(document, "target_service"));
        return command;
    }

    private void validate(ObjectMapper mapper, String targetService) {
        if (!ACTION_REFUND.equals(action)) {
            throw new RefundRejectedException(
                    RefundError.MALFORMED_COMMAND, "this service executes REFUND, not " + action);
        }
        if (!TARGET_SERVICE.equals(targetService)) {
            // Core-v1.2 has exactly one executor (docs/core-contracts.md:65). A command addressed at
            // another service is not one this service may execute, however well-formed the rest is.
            throw new RefundRejectedException(
                    RefundError.MALFORMED_COMMAND, "this command is addressed to " + targetService);
        }
        if (!"CNY".equals(currency)) {
            throw new RefundRejectedException(RefundError.MALFORMED_COMMAND, "core money is CNY, not " + currency);
        }
        if (quantity < 1 || quantity > MAX_QUANTITY) {
            throw new RefundRejectedException(RefundError.MALFORMED_COMMAND, "quantity is out of range: " + quantity);
        }
        if (amountMinor < 1 || amountMinor > MAX_AMOUNT_MINOR) {
            throw new RefundRejectedException(
                    RefundError.MALFORMED_COMMAND, "amount_minor is out of range: " + amountMinor);
        }
        if (inputRevision < 1) {
            throw new RefundRejectedException(RefundError.MALFORMED_COMMAND, "input_revision must be at least 1");
        }
        if (!payloadHash.matches("^[a-f0-9]{64}$")) {
            throw new RefundRejectedException(RefundError.MALFORMED_COMMAND, "payload_hash is not a sha-256 digest");
        }
        // The hash is re-derived rather than taken on trust: it is what the authorisation fixed
        // (docs/core-contracts.md:19), so a command whose hash does not cover its own members is a command
        // about a different payment than the one that was approved.
        String derived = payloadHash(mapper);
        if (!derived.equals(payloadHash)) {
            throw new RefundRejectedException(
                    RefundError.PAYLOAD_HASH_MISMATCH,
                    "payload_hash does not cover these members; the command and the authorisation disagree");
        }
    }

    /** The command document minus {@code payload_hash}, in the shape both languages hash. */
    public ObjectNode toJson(ObjectMapper mapper) {
        ObjectNode node = mapper.createObjectNode();
        node.put("operation_id", operationId);
        node.put("case_id", caseId);
        node.put("authorization_id", authorizationId);
        node.put("input_revision", inputRevision);
        node.put("line_id", lineId);
        node.put("merchant_id", merchantId);
        node.put("action", action);
        node.put("quantity", quantity);
        node.put("currency", currency);
        node.put("amount_minor", amountMinor);
        node.put("policy_version", policyVersion);
        node.put("target_service", TARGET_SERVICE);
        return node;
    }

    /** The hash this command must carry, derived from its own twelve members. */
    public String payloadHash(ObjectMapper mapper) {
        return CanonicalJson.payloadHash(toJson(mapper));
    }

    private static String requiredText(JsonNode document, String member) {
        JsonNode value = document.get(member);
        if (!value.isString() || value.stringValue().isBlank()) {
            throw new RefundRejectedException(RefundError.MALFORMED_COMMAND, member + " must be a non-empty string");
        }
        return value.stringValue();
    }

    private static long requiredPositive(JsonNode document, String member) {
        JsonNode value = document.get(member);
        if (!value.isIntegralNumber()) {
            // Float money is refused by the schema and by the canonicaliser (docs/contracts.md:19).
            throw new RefundRejectedException(RefundError.MALFORMED_COMMAND, member + " must be an integer");
        }
        return value.longValue();
    }
}
