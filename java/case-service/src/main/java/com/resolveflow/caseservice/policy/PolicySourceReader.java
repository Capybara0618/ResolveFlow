package com.resolveflow.caseservice.policy;

import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.time.Instant;
import java.time.format.DateTimeParseException;
import java.util.ArrayList;
import java.util.Comparator;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.stream.Stream;
import org.springframework.stereotype.Component;
import org.yaml.snakeyaml.Yaml;

/**
 * Reads a policy bundle source file and refuses anything a bundle may not be.
 *
 * <p>Every refusal names the file and the member, because the import is a controlled command run by a
 * person: "bundle is invalid" would leave them reading the parser. Validation is here rather than in the
 * database for the parts a database cannot state — a rule id used twice, an empty rule set, an instant
 * that is not UTC, a member nobody recognises.
 *
 * <p>Unknown members are refused instead of ignored. A bundle that quietly drops a misspelled member is a
 * bundle with fewer rules than its author believes, and the rules are what a refund decision cites.
 */
@Component
public class PolicySourceReader {

    private static final Set<String> BUNDLE_MEMBERS =
            Set.of("bundle_id", "version", "safety_epoch", "effective_from", "effective_to", "rules");
    private static final Set<String> RULE_MEMBERS = Set.of("rule_id", "title", "text");
    private static final int MAX_RULES = 200;

    /** A bundle that is well formed but may still collide with what is already stored. */
    public record Draft(
            String bundleId,
            String version,
            int safetyEpoch,
            Instant effectiveFrom,
            Instant effectiveTo,
            List<PolicyRule> rules,
            String sourcePath) {}

    /** A source file that cannot be accepted as a bundle. */
    public static class InvalidBundleException extends RuntimeException {

        private static final long serialVersionUID = 1L;

        public InvalidBundleException(String message) {
            super(message);
        }
    }

    /**
     * Every {@code *.yaml} file of a directory, read in file-name order.
     *
     * <p>Sorted so an import is reproducible: two runs over the same directory report the same things in the
     * same order, which is what makes the report worth reading.
     */
    public List<Draft> readDirectory(Path directory) {
        if (!Files.isDirectory(directory)) {
            throw new InvalidBundleException("not a directory: " + directory);
        }
        List<Path> files;
        try (Stream<Path> entries = Files.list(directory)) {
            files = entries.filter(path -> path.getFileName().toString().endsWith(".yaml"))
                    .sorted(Comparator.comparing(path -> path.getFileName().toString()))
                    .toList();
        } catch (IOException error) {
            throw new InvalidBundleException("cannot list " + directory + ": " + error.getMessage());
        }
        if (files.isEmpty()) {
            throw new InvalidBundleException("no *.yaml policy bundles in " + directory);
        }
        List<Draft> drafts = new ArrayList<>();
        for (Path file : files) {
            drafts.add(read(file));
        }
        return drafts;
    }

    public Draft read(Path file) {
        String source = file.toString();
        String text;
        try {
            text = Files.readString(file, StandardCharsets.UTF_8);
        } catch (IOException error) {
            throw new InvalidBundleException("cannot read " + source + ": " + error.getMessage());
        }
        Object parsed;
        try {
            parsed = new Yaml().load(text);
        } catch (RuntimeException error) {
            throw new InvalidBundleException(source + ": not valid YAML: " + error.getMessage());
        }
        if (!(parsed instanceof Map<?, ?> raw)) {
            throw new InvalidBundleException(source + ": a bundle must be a mapping");
        }
        Map<String, Object> members = new LinkedHashMap<>();
        raw.forEach((key, value) -> members.put(String.valueOf(key), value));
        requireKnownMembers(source, members, BUNDLE_MEMBERS);

        String bundleId = requireString(source, members, "bundle_id");
        String version = requireString(source, members, "version");
        int safetyEpoch = requireEpoch(source, members);
        Instant effectiveFrom = requireInstant(source, members, "effective_from");
        Instant effectiveTo = optionalInstant(source, members, "effective_to");
        if (effectiveTo != null && !effectiveTo.isAfter(effectiveFrom)) {
            throw new InvalidBundleException(
                    source + ": effective_to must be after effective_from, otherwise the version covers nothing");
        }
        List<PolicyRule> rules = readRules(source, members);

        return new Draft(bundleId, version, safetyEpoch, effectiveFrom, effectiveTo, rules, source);
    }

    private static List<PolicyRule> readRules(String file, Map<String, Object> members) {
        Object raw = members.get("rules");
        if (!(raw instanceof List<?> entries) || entries.isEmpty()) {
            throw new InvalidBundleException(
                    file + ": rules must be a non-empty list; a bundle with no rules decides nothing");
        }
        if (entries.size() > MAX_RULES) {
            throw new InvalidBundleException(file + ": at most " + MAX_RULES + " rules, found " + entries.size());
        }
        List<PolicyRule> rules = new ArrayList<>();
        Set<String> seen = new java.util.HashSet<>();
        for (Object entry : entries) {
            if (!(entry instanceof Map<?, ?> rawRule)) {
                throw new InvalidBundleException(file + ": every rule must be a mapping");
            }
            Map<String, Object> rule = new LinkedHashMap<>();
            rawRule.forEach((key, value) -> rule.put(String.valueOf(key), value));
            requireKnownMembers(file, rule, RULE_MEMBERS);
            String ruleId = requireString(file, rule, "rule_id");
            if (!seen.add(ruleId)) {
                throw new InvalidBundleException(file + ": rule_id " + ruleId + " appears twice in one bundle");
            }
            String title = requireString(file, rule, "title");
            String body = requireString(file, rule, "text");
            rules.add(new PolicyRule(ruleId, title, body));
        }
        return List.copyOf(rules);
    }

    private static void requireKnownMembers(String file, Map<String, Object> members, Set<String> allowed) {
        for (String member : members.keySet()) {
            if (!allowed.contains(member)) {
                throw new InvalidBundleException(
                        file + ": unknown member " + member + "; known members are " + allowed);
            }
        }
    }

    private static String requireString(String file, Map<String, Object> members, String member) {
        Object value = members.get(member);
        if (!(value instanceof String text) || text.isBlank()) {
            throw new InvalidBundleException(file + ": " + member + " is required and must be a non-empty string");
        }
        if (text.length() > 200 && !member.equals("text")) {
            throw new InvalidBundleException(file + ": " + member + " is too long");
        }
        return text;
    }

    private static int requireEpoch(String file, Map<String, Object> members) {
        Object value = members.get("safety_epoch");
        if (value == null) {
            return 0;
        }
        if (!(value instanceof Number number) || number.longValue() < 0) {
            throw new InvalidBundleException(file + ": safety_epoch must be a non-negative integer");
        }
        return (int) number.longValue();
    }

    private static Instant requireInstant(String file, Map<String, Object> members, String member) {
        Instant instant = optionalInstant(file, members, member);
        if (instant == null) {
            throw new InvalidBundleException(file + ": " + member + " is required");
        }
        return instant;
    }

    /**
     * An instant, and only in the one spelling the project uses: UTC with a trailing {@code Z}
     * (docs/engineering.md). An offset like {@code +08:00} is refused rather than silently normalised, so a
     * policy window cannot mean something different from what its author wrote.
     */
    private static Instant optionalInstant(String file, Map<String, Object> members, String member) {
        Object value = members.get(member);
        if (value == null) {
            return null;
        }
        String text = String.valueOf(value);
        if (!text.endsWith("Z")) {
            throw new InvalidBundleException(
                    file + ": " + member + " must be a UTC instant ending in Z, found " + text);
        }
        try {
            return Instant.parse(text);
        } catch (DateTimeParseException error) {
            throw new InvalidBundleException(file + ": " + member + " is not an instant: " + text);
        }
    }
}
