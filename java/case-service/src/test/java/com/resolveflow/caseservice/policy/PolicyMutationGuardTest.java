package com.resolveflow.caseservice.policy;

import static org.assertj.core.api.Assertions.assertThat;

import java.lang.reflect.Method;
import java.util.ArrayList;
import java.util.List;
import org.apache.ibatis.annotations.Delete;
import org.apache.ibatis.annotations.Insert;
import org.apache.ibatis.annotations.Select;
import org.apache.ibatis.annotations.Update;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

/**
 * The mapper has no way to change a stored policy version.
 *
 * <p>This test exists because the database could not be asked to enforce it: MySQL refuses {@code CREATE
 * TRIGGER} for an account without {@code SUPER} while binary logging is on (error 1419), and the service's own
 * account is not {@code SUPER}. Making the migration privileged would mean an immutability guarantee that
 * holds on one machine and not the next, which is worse than not claiming it.
 *
 * <p>So the claim is narrowed to what is checkable everywhere: the only statements the code can issue against
 * {@code policy_bundle} and {@code policy_rule} are inserts and reads. A future writer that adds an
 * {@code UPDATE} fails this test, which is the point at which someone should be asking why a version needs
 * editing rather than publishing a new one.
 *
 * <p>It reads the mapper's annotations rather than the whole application, deliberately: a test that scanned
 * every statement in the codebase would be a fuzzy search for the word UPDATE, while this states the exact
 * invariant — this table has one writer, and that writer only inserts.
 */
class PolicyMutationGuardTest {

    private static List<String> statements() {
        List<String> found = new ArrayList<>();
        for (Method method : PolicyRepository.class.getDeclaredMethods()) {
            Insert insert = method.getAnnotation(Insert.class);
            if (insert != null) {
                for (String value : insert.value()) {
                    found.add(value);
                }
            }
            Select select = method.getAnnotation(Select.class);
            if (select != null) {
                for (String value : select.value()) {
                    found.add(value);
                }
            }
            Update update = method.getAnnotation(Update.class);
            if (update != null) {
                for (String value : update.value()) {
                    found.add(value);
                }
            }
            Delete delete = method.getAnnotation(Delete.class);
            if (delete != null) {
                for (String value : delete.value()) {
                    found.add(value);
                }
            }
        }
        return found;
    }

    @Test
    @DisplayName("no statement against the policy tables is a mutation other than an insert")
    void policyTablesHaveNoMutationOtherThanInsert() {
        List<String> reads = new ArrayList<>();
        for (Method method : PolicyRepository.class.getDeclaredMethods()) {
            if (method.getAnnotation(Select.class) != null) {
                reads.add(method.getName());
            }
            assertThat(method.getAnnotation(Update.class))
                    .as("%s must not update a policy version", method.getName())
                    .isNull();
            assertThat(method.getAnnotation(Delete.class))
                    .as("%s must not delete policy rows", method.getName())
                    .isNull();
        }
        assertThat(reads)
                .as("the read path still exists, or the route would have nothing to serve")
                .isNotEmpty();

        for (String statement : statements()) {
            assertThat(statement.replaceAll("\\s+", " ").trim().toUpperCase(java.util.Locale.ROOT))
                    .as("only inserts and selects touch policy_bundle/policy_rule")
                    .matches("^(INSERT INTO POLICY_(BUNDLE|RULE)|SELECT )[\\s\\S]*");
        }
    }

    @Test
    @DisplayName("the two policy tables are the only ones this mapper writes, and rules keep their order")
    void theMapperWritesOnlyThePolicyTables() {
        List<String> inserts = new ArrayList<>();
        for (Method method : PolicyRepository.class.getDeclaredMethods()) {
            Insert insert = method.getAnnotation(Insert.class);
            if (insert != null) {
                inserts.add(String.join(" ", insert.value()));
            }
        }
        assertThat(inserts).hasSize(2);
        assertThat(inserts.toString()).contains("INSERT INTO policy_bundle").contains("INSERT INTO policy_rule");

        assertThat(statements().stream()
                        .filter(statement -> statement.contains("FROM policy_rule"))
                        .findFirst()
                        .orElseThrow())
                .as("a bundle is served in the order its author wrote, so the read must order by position")
                .contains("ORDER BY position");
    }
}
