package com.resolveflow.spike;

import com.alibaba.csp.sentinel.Entry;
import com.alibaba.csp.sentinel.SphU;
import com.alibaba.csp.sentinel.Tracer;
import com.alibaba.csp.sentinel.slots.block.BlockException;
import com.alibaba.csp.sentinel.slots.block.RuleConstant;
import com.alibaba.csp.sentinel.slots.block.degrade.DegradeRule;
import com.alibaba.csp.sentinel.slots.block.degrade.DegradeRuleManager;
import com.alibaba.csp.sentinel.slots.block.flow.FlowRule;
import com.alibaba.csp.sentinel.slots.block.flow.FlowRuleManager;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import java.util.List;
import java.util.concurrent.CopyOnWriteArrayList;
import java.util.concurrent.atomic.AtomicInteger;

import static org.assertj.core.api.Assertions.assertThat;

/**
 * T00 gate: does the SCA-managed Sentinel 1.8.9 actually enforce flow and degrade
 * rules on this stack? The project uses Sentinel to protect internal read
 * dependencies (docs/architecture.md), so "the starter resolved" is not enough —
 * a rule has to demonstrably fire.
 */
class SentinelIT {

    // Sentinel keeps rolling counters per resource name for the life of the JVM, so
    // each test uses its own resource; sharing one would leak traffic stats between tests.
    static final String FLOW_RESOURCE = "spike-flow-read";
    static final String DEGRADE_RESOURCE = "spike-degrade-read";
    static final String FREE_RESOURCE = "spike-unruled-read";

    @AfterEach
    void clearRules() {
        FlowRuleManager.loadRules(List.of());
        DegradeRuleManager.loadRules(List.of());
    }

    @Test
    @DisplayName("A flow rule throttles calls past the threshold")
    void flowRuleBlocksExcessTraffic() throws Exception {
        FlowRule rule = new FlowRule(FLOW_RESOURCE);
        rule.setGrade(RuleConstant.FLOW_GRADE_QPS);
        rule.setCount(1);
        FlowRuleManager.loadRules(List.of(rule));

        AtomicInteger passed = new AtomicInteger();
        AtomicInteger blocked = new AtomicInteger();

        // Sentinel's QPS window is 1s; 20 back-to-back calls must not all pass.
        for (int i = 0; i < 20; i++) {
            try (Entry entry = SphU.entry(FLOW_RESOURCE)) {
                passed.incrementAndGet();
            } catch (BlockException e) {
                blocked.incrementAndGet();
            }
        }

        assertThat(passed.get()).as("at least one call passes").isGreaterThanOrEqualTo(1);
        assertThat(blocked.get()).as("the rule must actually block excess traffic").isGreaterThan(0);
        assertThat(passed.get() + blocked.get()).isEqualTo(20);
    }

    @Test
    @DisplayName("A degrade rule opens the circuit after repeated failures")
    void degradeRuleOpensCircuit() throws Exception {
        DegradeRule rule = new DegradeRule(DEGRADE_RESOURCE)
                .setGrade(RuleConstant.DEGRADE_GRADE_EXCEPTION_COUNT)
                .setCount(3)
                .setTimeWindow(10)
                .setMinRequestAmount(3)
                .setStatIntervalMs(1_000);
        DegradeRuleManager.loadRules(List.of(rule));

        AtomicInteger upstreamCalls = new AtomicInteger();
        AtomicInteger shortCircuited = new AtomicInteger();

        for (int i = 0; i < 10; i++) {
            try (Entry entry = SphU.entry(DEGRADE_RESOURCE)) {
                upstreamCalls.incrementAndGet();
                // Simulate the protected dependency failing.
                Tracer.trace(new IllegalStateException("upstream read failed"));
                throw new IllegalStateException("upstream read failed");
            } catch (BlockException e) {
                shortCircuited.incrementAndGet();
            } catch (IllegalStateException expected) {
                // counted by Tracer above
            }
        }

        assertThat(shortCircuited.get())
                .as("after the threshold the circuit must short-circuit instead of calling upstream")
                .isGreaterThan(0);
        assertThat(upstreamCalls.get())
                .as("the circuit must stop sending traffic to the failing dependency")
                .isLessThan(10);
    }

    @Test
    @DisplayName("Without rules, nothing is blocked")
    void noRulesMeansNoBlocking() throws Exception {
        List<String> blocked = new CopyOnWriteArrayList<>();
        for (int i = 0; i < 5; i++) {
            try (Entry entry = SphU.entry(FREE_RESOURCE)) {
                // allowed
            } catch (BlockException e) {
                blocked.add(e.getClass().getSimpleName());
            }
        }
        assertThat(blocked).isEmpty();
    }
}