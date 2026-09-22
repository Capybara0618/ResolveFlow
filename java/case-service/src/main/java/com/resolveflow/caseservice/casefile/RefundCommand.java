package com.resolveflow.caseservice.casefile;

import com.resolveflow.shared.contract.CanonicalJson;
import tools.jackson.databind.ObjectMapper;
import tools.jackson.databind.node.ObjectNode;

/**
 * The twelve fields a refund command is, in one place (contracts/core/refund-command.schema.json).
 *
 * <p>This record exists because two different moments need the same twelve values: the authorisation fixes
 * the payload hash at creation (C03.3a), and the command that is eventually sent carries those same values
 * (C04). Building the node in one method is what keeps "what was approved" and "what was executed" from
 * being two independently assembled objects that merely look alike — the hash is over this node, and the
 * command is this node plus the hash.
 *
 * <p>{@code payload_hash} is not a member here: it is the hash of the others, and a field that hashed
 * itself would be a contradiction. {@code target_service} is a constant because core-v1.2 has exactly one
 * executor.
 */
public record RefundCommand(
        String operationId,
        String caseId,
        String authorizationId,
        int inputRevision,
        String lineId,
        String merchantId,
        ExecutableAction action,
        int quantity,
        String currency,
        long amountMinor,
        String policyVersion) {

    /** The one service a core execution command can be addressed to (docs/core-contracts.md:65). */
    public static final String TARGET_SERVICE = "commerce-service";

    /** The command as the JSON its consumer receives, minus {@code payload_hash}. */
    public ObjectNode toJson(ObjectMapper mapper) {
        ObjectNode node = mapper.createObjectNode();
        node.put("operation_id", operationId);
        node.put("case_id", caseId);
        node.put("authorization_id", authorizationId);
        node.put("input_revision", inputRevision);
        node.put("line_id", lineId);
        node.put("merchant_id", merchantId);
        node.put("action", action.wire());
        node.put("quantity", quantity);
        node.put("currency", currency);
        node.put("amount_minor", amountMinor);
        node.put("policy_version", policyVersion);
        node.put("target_service", TARGET_SERVICE);
        return node;
    }

    /**
     * The hash this command's consumer has to verify.
     *
     * <p>Computed from the node above rather than stored twice, and computed the same way in Java and in
     * Python (docs/contracts.md:17): the consumer re-derives it from what it received.
     */
    public String payloadHash(ObjectMapper mapper) {
        return CanonicalJson.payloadHash(toJson(mapper));
    }
}
