package com.resolveflow.caseservice.policy;

import com.resolveflow.shared.contract.CanonicalJson;
import tools.jackson.databind.ObjectMapper;
import tools.jackson.databind.node.ObjectNode;

/**
 * One rule of a bundle, member for member with the contract's {@code PolicyRule}.
 *
 * <p>The contract's {@code PolicyRef} requires a {@code chunk_id} and a {@code content_hash}, so the route
 * that serves rules has to publish both: a run that had to guess the hash could never pass the check, and a
 * check nobody can pass is not a check. Both are <b>derived from the stored rule</b> — never read from the
 * file the bundle was imported from, and never stored — for the same reason the bundle's own manifest hash is
 * derived (C03.1a): a hash that came from outside the content could disagree with the content.
 *
 * <p>The chunk is the rule. Core has no retrieval index yet (that is C07's), so the unit a citation can name
 * is the unit this service can serve and re-hash: one rule, identified inside its bundle by its position
 * ({@code c-01}, {@code c-02}, …) and hashed together with the bundle id, so the same wording in two versions
 * is two different citations — which is the point of citing a version at all.
 *
 * <p>{@code position} is still not a member: the order is the source file's, kept in storage, and it is what
 * makes a chunk id reproducible on every read rather than dependent on what a database returned first.
 */
public record PolicyRule(String ruleId, String title, String text, String chunkId, String contentHash) {

    /** Chunks are numbered from one, zero-padded, so {@code c-01} sorts before {@code c-10}. */
    public static String chunkIdFor(int position) {
        return String.format("c-%02d", position);
    }

    /**
     * Rebuild a rule with its derived members, from what the database holds.
     *
     * <p>{@code storedPosition} is the rule's place in the bundle as it was written, which is also what the
     * service serves the rules in: the same position is the same chunk id on every read, so a hash a run copied
     * from this route stays the hash this service computes when it re-checks the citation. Storage counts from
     * zero ({@code policy_rule.position}) and citations count from one ({@code c-01}, as the contract's example
     * writes it); the conversion happens here and nowhere else.
     */
    public static PolicyRule from(String bundleId, int storedPosition, String ruleId, String title, String text) {
        String chunkId = chunkIdFor(storedPosition + 1);
        return new PolicyRule(ruleId, title, text, chunkId, hash(bundleId, chunkId, title, text));
    }

    /**
     * The hash a citation of this rule must carry.
     *
     * <p>Canonical JSON over the four members, so two services that agree on the shape agree on the bytes and
     * therefore on the hash (contracts/core/canonical.md). It is the same construction the bundle's manifest
     * hash uses, which is why a test can compare the two without special cases.
     */
    public static String hash(String bundleId, String chunkId, String title, String text) {
        ObjectNode node = new ObjectMapper().createObjectNode();
        node.put("bundle_id", bundleId);
        node.put("chunk_id", chunkId);
        node.put("title", title);
        node.put("text", text);
        return CanonicalJson.contentHash(node);
    }
}
