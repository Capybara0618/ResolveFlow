package com.resolveflow.caseservice.policy;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

import com.resolveflow.caseservice.CaseDatabaseTest;
import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.List;
import java.util.Map;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.io.TempDir;
import org.springframework.beans.factory.annotation.Autowired;

/**
 * The controlled policy import (docs/core-contracts.md:50,53).
 *
 * <p>The tests are about the properties a version has to have for a decision to be checkable later: the hash
 * comes from the content, importing twice changes nothing, importing different content under the same id is
 * refused and leaves the stored version alone, and two versions cannot cover the same payment time.
 */
class PolicyImportTest extends CaseDatabaseTest {

    @Autowired
    PolicyImportService imports;

    @Autowired
    PolicySourceReader reader;

    @TempDir
    Path temp;

    @BeforeEach
    void clean() {
        // The rule table cascades from the bundle, so cleanup deletes the child rows first and
        // then the versions themselves.
        jdbc.execute("DELETE FROM policy_rule");
        jdbc.execute("DELETE FROM policy_bundle");
    }

    private Path bundle(String name, String content) throws IOException {
        Path file = temp.resolve(name);
        Files.writeString(file, content, StandardCharsets.UTF_8);
        return file;
    }

    private static String source(String bundleId, String from, String to, int epoch, String... ruleIds) {
        return source(bundleId, "M-1001", from, to, epoch, ruleIds);
    }

    /**
     * One bundle source file.
     *
     * <p>{@code merchantId} is a parameter with a default rather than a constant, because after C07.1 two
     * merchants publishing on the same date is the ordinary case: a test that could only write M-1001's
     * bundles could not tell "the window check is per merchant" from "the check never fires".
     */
    private static String source(
            String bundleId, String merchantId, String from, String to, int epoch, String... ruleIds) {
        StringBuilder text = new StringBuilder();
        text.append("bundle_id: ").append(bundleId).append('\n');
        text.append("merchant_id: ").append(merchantId).append('\n');
        text.append("version: \"2026.09\"\n");
        text.append("safety_epoch: ").append(epoch).append('\n');
        text.append("effective_from: \"").append(from).append("\"\n");
        text.append("effective_to: ")
                .append(to == null ? "null" : "\"" + to + "\"")
                .append('\n');
        text.append("rules:\n");
        for (String ruleId : ruleIds) {
            text.append("  - rule_id: ").append(ruleId).append('\n');
            text.append("    title: 标题 ").append(ruleId).append('\n');
            text.append("    text: 规则正文 ").append(ruleId).append('\n');
        }
        return text.toString();
    }

    private Map<String, Object> storedBundle(String bundleId) {
        return jdbc.queryForMap(
                "SELECT version, manifest_hash, safety_epoch, effective_from, effective_to FROM policy_bundle WHERE bundle_id = ?",
                bundleId);
    }

    @Test
    @DisplayName("a bundle is stored with a hash of its content, and its rules in source order")
    void aBundleIsStoredWithItsHash() throws IOException {
        Path file = bundle(
                "a.yaml",
                source("policy-logistics-2026.09", "2026-09-01T00:00:00Z", null, 2, "R-LOST-001", "R-NOSCAN-7D"));

        PolicyImportService.Report report = imports.importDirectory(temp);

        assertThat(report.imported()).hasSize(1);
        assertThat(report.skipped()).isEmpty();
        Map<String, Object> stored = storedBundle("policy-logistics-2026.09");
        assertThat(stored.get("manifest_hash").toString()).matches("[a-f0-9]{64}");
        assertThat(stored.get("safety_epoch")).isEqualTo(2);
        assertThat(stored.get("effective_to")).isNull();

        List<String> ruleIds = jdbc.queryForList(
                "SELECT rule_id FROM policy_rule WHERE bundle_id = ? ORDER BY position",
                String.class,
                "policy-logistics-2026.09");
        assertThat(ruleIds)
                .as("the order the file wrote, not an order the database chose")
                .containsExactly("R-LOST-001", "R-NOSCAN-7D");

        // The hash is a function of the content: the same draft hashes the same, a changed rule does not.
        PolicySourceReader.Draft draft = reader.read(file);
        assertThat(imports.hash(draft)).isEqualTo(stored.get("manifest_hash"));
        PolicySourceReader.Draft changed = new PolicySourceReader.Draft(
                draft.bundleId(),
                draft.merchantId(),
                draft.version(),
                draft.safetyEpoch(),
                draft.effectiveFrom(),
                draft.effectiveTo(),
                List.of(new PolicySourceReader.SourceRule("R-LOST-001", "标题 R-LOST-001", "改动过的正文")),
                draft.sourcePath());
        assertThat(imports.hash(changed)).isNotEqualTo(stored.get("manifest_hash"));
    }

    @Test
    @DisplayName("importing the same bundle twice is a skip, not a second version")
    void importingTwiceIsIdempotent() throws IOException {
        bundle("a.yaml", source("policy-logistics-2026.09", "2026-09-01T00:00:00Z", null, 2, "R-LOST-001"));

        assertThat(imports.importDirectory(temp).imported()).hasSize(1);
        PolicyImportService.Report second = imports.importDirectory(temp);

        assertThat(second.imported()).isEmpty();
        assertThat(second.skipped()).hasSize(1);
        assertThat(jdbc.queryForObject(
                        "SELECT COUNT(*) FROM policy_rule WHERE bundle_id = ?",
                        Integer.class,
                        "policy-logistics-2026.09"))
                .as("a re-import must not duplicate the rules")
                .isEqualTo(1);
    }

    @Test
    @DisplayName("different content under an imported id is refused, and the stored version is untouched")
    void anImportedVersionCannotBeChanged() throws IOException {
        bundle("a.yaml", source("policy-logistics-2026.09", "2026-09-01T00:00:00Z", null, 2, "R-LOST-001"));
        imports.importDirectory(temp);
        String before =
                storedBundle("policy-logistics-2026.09").get("manifest_hash").toString();

        // Same id, one more rule: exactly the edit versioning exists to prevent.
        Files.delete(temp.resolve("a.yaml"));
        bundle(
                "a.yaml",
                source("policy-logistics-2026.09", "2026-09-01T00:00:00Z", null, 3, "R-LOST-001", "R-NEW-001"));

        assertThatThrownBy(() -> imports.importDirectory(temp))
                .isInstanceOf(PolicyImportService.ImportRefusedException.class)
                .hasMessageContaining("version is immutable");

        assertThat(storedBundle("policy-logistics-2026.09").get("manifest_hash").toString())
                .as("the stored version is the one cases were decided against")
                .isEqualTo(before);
        assertThat(jdbc.queryForObject(
                        "SELECT COUNT(*) FROM policy_rule WHERE bundle_id = ?",
                        Integer.class,
                        "policy-logistics-2026.09"))
                .isEqualTo(1);
    }

    @Test
    @DisplayName("two merchants may publish a version at the same instant; one merchant may not")
    void theWindowRulesAreScopedToTheMerchant() throws IOException {
        // Both merchants start a version on the same date. Before C07.1 this was refused as "two policies
        // and no way to choose" - which was true only while the policy table held one merchant's rules.
        bundle("a.yaml", source("policy-logistics-2026.09", "M-1001", "2026-09-01T00:00:00Z", null, 2, "R-1"));
        bundle("b.yaml", source("policy-damage-2026.09", "M-2002", "2026-09-01T00:00:00Z", null, 2, "R-2"));

        assertThat(imports.importDirectory(temp).imported())
                .as("a second merchant is not a collision")
                .hasSize(2);

        // The same merchant publishing a second version at that instant still is one: a payment then would
        // have two of *this merchant's* policies and no way to choose between them.
        Files.delete(temp.resolve("b.yaml"));
        bundle("c.yaml", source("policy-logistics-2026.09-bis", "M-1001", "2026-09-01T00:00:00Z", null, 2, "R-3"));
        assertThatThrownBy(() -> imports.importDirectory(temp))
                .isInstanceOf(PolicyImportService.ImportRefusedException.class)
                .hasMessageContaining("no way to choose")
                .hasMessageContaining("policy-logistics-2026.09");
    }

    @Test
    @DisplayName("the merchant is part of the bundle's identity, and therefore of its hash")
    void theMerchantIsPartOfTheHash() throws IOException {
        Path file =
                bundle("a.yaml", source("policy-logistics-2026.09", "M-1001", "2026-09-01T00:00:00Z", null, 2, "R-1"));
        PolicySourceReader.Draft mine = reader.read(file);
        PolicySourceReader.Draft theirs = new PolicySourceReader.Draft(
                mine.bundleId(),
                "M-2002",
                mine.version(),
                mine.safetyEpoch(),
                mine.effectiveFrom(),
                mine.effectiveTo(),
                mine.rules(),
                mine.sourcePath());

        // Identical rules, two merchants: two manifests. If the hash ignored the merchant, a case could pin
        // a hash that does not say whose rules it is, and "whose policy did this decision cite" would be
        // unanswerable from the pin (docs/policy-rag.md:15).
        assertThat(imports.hash(theirs)).isNotEqualTo(imports.hash(mine));

        // And a source with no merchant is refused rather than attributed by default.
        Files.delete(file);
        bundle(
                "d.yaml",
                source("policy-logistics-2026.09", "2026-09-01T00:00:00Z", null, 2, "R-1")
                        .replace("merchant_id: M-1001\n", ""));
        assertThatThrownBy(() -> imports.importDirectory(temp))
                .isInstanceOf(PolicySourceReader.InvalidBundleException.class)
                .hasMessageContaining("merchant_id is required");
    }

    @Test
    @DisplayName("a newer version may supersede an open one, but not cross an explicit end")
    void aNewerVersionSupersedesRatherThanOverlaps() throws IOException {
        bundle("a.yaml", source("policy-logistics-2026.08", "2026-08-01T00:00:00Z", "2026-09-01T00:00:00Z", 1, "R-1"));
        imports.importDirectory(temp);

        Files.delete(temp.resolve("a.yaml"));
        bundle("b.yaml", source("policy-logistics-2026.09", "2026-08-15T00:00:00Z", null, 2, "R-1"));
        assertThatThrownBy(() -> imports.importDirectory(temp))
                .isInstanceOf(PolicyImportService.ImportRefusedException.class)
                .hasMessageContaining("crosses policy-logistics-2026.08")
                .hasMessageContaining("explicit end");

        Files.delete(temp.resolve("b.yaml"));
        // Starting after a gap is fine: a payment before any published policy genuinely has none.
        bundle("c.yaml", source("policy-logistics-2026.09", "2026-09-05T00:00:00Z", null, 2, "R-1"));
        assertThat(imports.importDirectory(temp).imported()).hasSize(1);

        // The open version can be superseded: this is what publishing a new policy is. Refusing it
        // would mean a policy set that can never move on, because the next version always overlaps
        // the one with no end — and closing that one would be editing an immutable version.
        Files.delete(temp.resolve("c.yaml"));
        bundle("d.yaml", source("policy-logistics-2026.10", "2026-10-01T00:00:00Z", null, 3, "R-1"));
        assertThat(imports.importDirectory(temp).imported()).hasSize(1);

        // A version that starts before an installed one would rewrite history rather than continue it.
        Files.delete(temp.resolve("d.yaml"));
        bundle("e.yaml", source("policy-logistics-2026.09.5", "2026-09-20T00:00:00Z", null, 4, "R-1"));
        assertThatThrownBy(() -> imports.importDirectory(temp)).hasMessageContaining("does not rewrite it");

        // And two versions starting at the same instant would leave a payment with two policies.
        Files.delete(temp.resolve("e.yaml"));
        bundle("f.yaml", source("policy-logistics-2026.10-bis", "2026-10-01T00:00:00Z", null, 4, "R-1"));
        assertThatThrownBy(() -> imports.importDirectory(temp)).hasMessageContaining("no way to choose");
    }

    @Test
    @DisplayName("a source that is not a bundle is refused with the reason, before anything is stored")
    void invalidSourcesAreRefused() throws IOException {
        bundle(
                "bad-unknown-member.yaml",
                source("policy-a", "2026-09-01T00:00:00Z", null, 1, "R-1") + "published: true\n");
        assertThatThrownBy(() -> imports.importDirectory(temp))
                .isInstanceOf(PolicySourceReader.InvalidBundleException.class)
                .hasMessageContaining("unknown member published");

        Files.delete(temp.resolve("bad-unknown-member.yaml"));
        bundle("bad-duplicate-rule.yaml", source("policy-a", "2026-09-01T00:00:00Z", null, 1, "R-1", "R-1"));
        assertThatThrownBy(() -> imports.importDirectory(temp)).hasMessageContaining("appears twice in one bundle");

        Files.delete(temp.resolve("bad-duplicate-rule.yaml"));
        bundle("bad-no-rules.yaml", source("policy-a", "2026-09-01T00:00:00Z", null, 1));
        assertThatThrownBy(() -> imports.importDirectory(temp)).hasMessageContaining("rules must be a non-empty list");

        Files.delete(temp.resolve("bad-no-rules.yaml"));
        bundle("bad-window.yaml", source("policy-a", "2026-09-01T00:00:00Z", "2026-09-01T00:00:00Z", 1, "R-1"));
        assertThatThrownBy(() -> imports.importDirectory(temp))
                .hasMessageContaining("effective_to must be after effective_from");

        Files.delete(temp.resolve("bad-window.yaml"));
        // An offset instant is refused rather than normalised: the window must mean what its author wrote.
        bundle("bad-instant.yaml", source("policy-a", "2026-09-01T08:00:00+08:00", null, 1, "R-1"));
        assertThatThrownBy(() -> imports.importDirectory(temp)).hasMessageContaining("ending in Z");

        assertThat(jdbc.queryForObject("SELECT COUNT(*) FROM policy_bundle", Integer.class))
                .as("nothing invalid reached storage")
                .isZero();
    }
}
