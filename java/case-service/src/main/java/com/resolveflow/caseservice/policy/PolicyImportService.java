package com.resolveflow.caseservice.policy;

import com.resolveflow.shared.contract.CanonicalJson;
import java.time.Clock;
import java.time.Instant;
import java.util.ArrayList;
import java.util.List;
import org.springframework.stereotype.Service;
import tools.jackson.databind.ObjectMapper;
import tools.jackson.databind.node.ArrayNode;
import tools.jackson.databind.node.ObjectNode;

/**
 * Imports policy bundles: validate, hash, store once, never edit (docs/core-contracts.md:50,53).
 *
 * <p>Three rules make "an immutable version" mean something:
 *
 * <ol>
 *   <li><b>The hash is computed from the content, not read from the file.</b> A bundle that carried its own
 *       hash would let a file claim one thing and contain another, and the hash is what later proves the
 *       rules a decision cited are the rules that were in force.
 *   <li><b>Re-importing the same content is a skip, not a second version.</b> Running the command twice is
 *       an ordinary thing to do — after a deploy, on a fresh database — so it is idempotent and says so.
 *   <li><b>Re-importing different content under an existing bundle_id is refused.</b> This is the whole
 *       point of versioning: cases were decided against those rules. The refusal names the stored hash and
 *       the new one, and the stored row is left alone.
 * </ol>
 *
 * <p>Windows must not overlap across bundles. Selection is by payment time (docs/core-contracts.md:50), so
 * two versions covering the same instant would make which policy applied depend on row order. Gaps are
 * allowed and are not the same thing: a payment before any published policy genuinely has none, and that
 * has to be handled explicitly rather than by silently borrowing the nearest version.
 */
@Service
public class PolicyImportService {

    private final PolicySourceReader reader;
    private final PolicyWriter writer;
    private final Clock clock;
    private final ObjectMapper mapper = new ObjectMapper();

    public PolicyImportService(PolicySourceReader reader, PolicyWriter writer, Clock clock) {
        this.reader = reader;
        this.writer = writer;
        this.clock = clock;
    }

    /** What one import did, file by file, so the operator sees which of their files did nothing. */
    public record Report(List<String> imported, List<String> skipped) {

        public String describe() {
            return "imported " + imported.size() + " " + imported + ", skipped " + skipped.size() + " " + skipped;
        }
    }

    /** A source that cannot be imported: it names the bundle and why. */
    public static class ImportRefusedException extends RuntimeException {

        private static final long serialVersionUID = 1L;

        public ImportRefusedException(String message) {
            super(message);
        }
    }

    /**
     * Imports every bundle of a directory.
     *
     * <p>Files are stored one at a time, so a refusal names the file that caused it and the bundles before it
     * are already in place. That is deliberate for a controlled command: an operator fixing one bad file
     * should not have to re-import the good ones, and the operation is idempotent anyway.
     */
    public Report importDirectory(java.nio.file.Path directory) {
        List<String> imported = new ArrayList<>();
        List<String> skipped = new ArrayList<>();
        for (PolicySourceReader.Draft draft : reader.readDirectory(directory)) {
            String manifestHash = hash(draft);
            if (writer.write(draft, manifestHash, Instant.now(clock))) {
                imported.add(draft.bundleId() + " (" + draft.rules().size() + " rules, " + manifestHash + ")");
            } else {
                skipped.add(draft.bundleId() + " (already imported with the same hash)");
            }
        }
        return new Report(List.copyOf(imported), List.copyOf(skipped));
    }

    /**
     * The hash of the bundle's content: identity, version, epoch and every rule in order.
     *
     * <p>Canonical JSON of exactly these members, so the hash is reproducible from the source and a change to
     * any rule changes it. The file path is not part of it: the same bundle copied to another directory is
     * the same bundle.
     */
    public String hash(PolicySourceReader.Draft draft) {
        ObjectNode node = mapper.createObjectNode();
        node.put("bundle_id", draft.bundleId());
        node.put("version", draft.version());
        node.put("safety_epoch", draft.safetyEpoch());
        node.put("effective_from", draft.effectiveFrom().toString());
        node.put(
                "effective_to",
                draft.effectiveTo() == null ? null : draft.effectiveTo().toString());
        ArrayNode rules = node.putArray("rules");
        for (PolicySourceReader.SourceRule rule : draft.rules()) {
            ObjectNode item = rules.addObject();
            item.put("rule_id", rule.ruleId());
            item.put("title", rule.title());
            item.put("text", rule.text());
        }
        return CanonicalJson.contentHash(node);
    }
}
