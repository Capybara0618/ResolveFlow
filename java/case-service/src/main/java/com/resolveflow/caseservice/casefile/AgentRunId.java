package com.resolveflow.caseservice.casefile;

import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.util.UUID;

/**
 * The run a case revision is investigated by, derived rather than generated.
 *
 * <p>The contract says case-service derives it from {@code (case_id, input_revision)}
 * (contracts/core/openapi-agent.yaml:59), and the reason is what a retry needs: a run id invented per
 * attempt would open a <em>second</em> run for the same revision every time a delivery was redelivered,
 * and the Agent's idempotent intake — the thing that makes 202 safe to retry — would have nothing to be
 * idempotent about.
 *
 * <p>This is RFC 9562 version 5 (name-based, SHA-1). It is written out rather than taken from
 * {@link UUID#nameUUIDFromBytes}, which is version <b>3</b> (MD5): calling it would have produced a
 * perfectly deterministic id under a label that says it is something else, and the version nibble is the
 * one part of a UUID whose whole job is to be checkable. The hash input is the namespace in its canonical
 * string form followed by the name, both as UTF-8, which is what the standard prescribes.
 *
 * <p>Two properties follow and both are asserted: the same pair always yields the same id (across restarts
 * and across processes, not just within one run), and a different pair yields a different one — a revision
 * of a case is a different investigation from the revision before it.
 */
public final class AgentRunId {

    /**
     * The namespace for run ids, minted once for this purpose.
     *
     * <p>Replacing it would renumber every future run, so it is a constant rather than a value read from
     * configuration: the derivation has to mean the same thing in a restarted process as in the one that
     * wrote the binding.
     */
    private static final UUID RUN_NAMESPACE = UUID.fromString("6b3f2c1a-9d4e-5f60-8a71-2c3d4e5f6a7b");

    private AgentRunId() {}

    /** The one run id for this case's revision. */
    public static String forRevision(String caseId, int inputRevision) {
        if (caseId == null || caseId.isBlank()) {
            throw new IllegalArgumentException("a case id is required to derive a run id");
        }
        if (inputRevision < 1) {
            // The contract's InputRevision starts at 1 (contracts/core/openapi-agent.yaml:320); a run for
            // revision 0 would name a revision no case can be in.
            throw new IllegalArgumentException("input_revision must be at least 1, got " + inputRevision);
        }
        byte[] digest = sha1((RUN_NAMESPACE + ":" + caseId + ":" + inputRevision).getBytes(StandardCharsets.UTF_8));
        // The low 6 bits of octet 8 are replaced by the variant (10 = RFC 9562), and the high 4 bits of
        // octet 6 by the version (5). The other 122 bits are the hash.
        digest[6] = (byte) ((digest[6] & 0x0f) | 0x50);
        digest[8] = (byte) ((digest[8] & 0x3f) | 0x80);
        long most = 0;
        long least = 0;
        for (int index = 0; index < 8; index++) {
            most = (most << 8) | (digest[index] & 0xffL);
            least = (least << 8) | (digest[index + 8] & 0xffL);
        }
        return new UUID(most, least).toString();
    }

    private static byte[] sha1(byte[] input) {
        try {
            return MessageDigest.getInstance("SHA-1").digest(input);
        } catch (NoSuchAlgorithmException missing) {
            // SHA-1 is required of every Java platform, so this cannot happen on a conforming runtime.
            throw new IllegalStateException("SHA-1 is unavailable, so run ids cannot be derived", missing);
        }
    }
}
