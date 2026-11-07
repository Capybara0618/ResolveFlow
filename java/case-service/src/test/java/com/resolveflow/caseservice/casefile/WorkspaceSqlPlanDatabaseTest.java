package com.resolveflow.caseservice.casefile;

import static org.assertj.core.api.Assertions.*;

import com.resolveflow.caseservice.CaseDatabaseTest;
import com.resolveflow.shared.security.*;
import java.nio.file.*;
import java.sql.*;
import java.time.Instant;
import java.util.*;
import org.apache.ibatis.executor.statement.StatementHandler;
import org.apache.ibatis.plugin.*;
import org.apache.ibatis.session.*;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import tools.jackson.databind.ObjectMapper;

class WorkspaceSqlPlanDatabaseTest extends CaseDatabaseTest {
    @Autowired
    SqlSessionFactory sessions;

    @Autowired
    ReviewQueueService queue;

    @Autowired
    io.micrometer.core.instrument.MeterRegistry metrics;

    static final class Probe implements Interceptor {
        boolean active;
        final List<Map<String, Object>> rows = new ArrayList<>();

        @Override
        public Object intercept(Invocation call) throws Throwable {
            Object result = call.proceed();
            if (!active) return result;
            var handler = (StatementHandler) call.getTarget();
            String sql = handler.getBoundSql().getSql();
            var statement = (Statement) call.getArgs()[0];
            var plan = new ArrayList<String>();
            try (var explain = statement.getConnection().prepareStatement("EXPLAIN ANALYZE " + sql)) {
                handler.getParameterHandler().setParameters(explain);
                try (var output = explain.executeQuery()) {
                    while (output.next()) plan.add(output.getString(1));
                }
            }
            rows.add(Map.of(
                    "sql",
                    sql,
                    "parameters",
                    handler.getParameterHandler().getParameterObject().toString(),
                    "plan",
                    plan));
            return result;
        }

        @Override
        public Object plugin(Object target) {
            if (!(target instanceof StatementHandler)) return target;
            return Plugin.wrap(target, this);
        }
    }

    @Intercepts(
            @Signature(
                    type = StatementHandler.class,
                    method = "query",
                    args = {Statement.class, ResultHandler.class}))
    static final class RecordingProbe implements Interceptor {
        final Probe delegate = new Probe();

        @Override
        public Object intercept(Invocation call) throws Throwable {
            return delegate.intercept(call);
        }
    }

    @Test
    void actualWorkspaceProfilesKeepScopedProjectionAndRecordExistingIndexPlans() throws Exception {
        registerTestAccount("d4-ws-a", "D4-WS1", "REVIEWER", null);
        registerTestAccount("d4-ws-b", "D4-WS2", "REVIEWER", null);
        var values = new ArrayList<Object[]>();
        var at = Timestamp.from(Instant.parse("2026-10-26T00:00:00Z"));
        for (int i = 0; i < 20000; i++)
            values.add(new Object[] {
                new UUID(0, i + 100000).toString(),
                i % 2 == 0 ? "D4-WS1" : "D4-WS2",
                "D4-CUSTOMER",
                new UUID(1, i + 100000).toString(),
                "D4-WS-L" + i,
                "needle " + i,
                List.of("PENDING_REVIEW", "WAITING_CUSTOMER", "EXECUTING", "CLOSED_SUCCESS", "QUEUED")
                        .get(i % 5),
                at,
                at
            });
        jdbc.batchUpdate(
                "INSERT INTO aftersale_case(case_id,merchant_id,buyer_id,order_id,line_id,description,status,input_revision,version,created_at,updated_at) VALUES(?,?,?,?,?,?,?,1,1,?,?)",
                values);
        jdbc.update(
                "INSERT INTO case_requested_action SELECT case_id,'REFUND' FROM aftersale_case WHERE merchant_id IN ('D4-WS1','D4-WS2')");
        jdbc.update(
                "INSERT INTO case_collaboration(case_id,owner_username,version,updated_at) SELECT case_id,IF(merchant_id='D4-WS1','d4-ws-a','d4-ws-b'),1,updated_at FROM aftersale_case WHERE merchant_id IN ('D4-WS1','D4-WS2') AND MOD(CAST(SUBSTRING(line_id,8) AS UNSIGNED),3)=0");
        jdbc.execute("ANALYZE TABLE aftersale_case,case_collaboration,case_requested_action");
        var interceptor = new RecordingProbe();
        sessions.getConfiguration().addInterceptor(interceptor);
        var probe = interceptor.delegate;
        var first = new AuthenticatedPrincipal("d4-ws-a", "D4-WS1", Role.REVIEWER, null);
        var second = new AuthenticatedPrincipal("d4-ws-b", "D4-WS2", Role.REVIEWER, null);
        var all = new ArrayList<Map<String, Object>>();
        ReviewQueueService.Page previous = null;
        try {
            for (String profile :
                    List.of("REVIEW_PUBLIC", "REVIEW_NEXT", "MINE", "UNCLAIMED", "SEARCH", "SECOND_STORE", "ALL")) {
                var principal = profile.equals("SECOND_STORE") ? second : first;
                String stage = profile.equals("ALL") ? "ALL" : "REVIEW";
                String scope = profile.equals("MINE") ? "MINE" : profile.equals("UNCLAIMED") ? "UNCLAIMED" : "PUBLIC";
                String search = profile.equals("SEARCH") ? "needle 10" : "";
                String cursor = profile.equals("REVIEW_NEXT") ? previous.nextCursor() : null;
                probe.rows.clear();
                probe.active = true;
                var page = queue.workspace(principal, cursor, 20, stage, search, scope);
                probe.active = false;
                assertThat(probe.rows).hasSize(3);
                assertThat(page.items())
                        .hasSize(20)
                        .allSatisfy(
                                item -> assertThat(item.requestedActions()).containsExactly(RequestedAction.REFUND));
                if (profile.equals("REVIEW_PUBLIC")) {
                    assertThat(page.counts().total()).isEqualTo(2000);
                    previous = page;
                }
                if (profile.equals("REVIEW_NEXT")) {
                    var prior = previous;
                    assertThat(page.items()).noneMatch(item -> previousItem(prior, item));
                }
                var expected = jdbc.queryForList(
                        "SELECT case_id FROM aftersale_case WHERE merchant_id=?", String.class, principal.merchantId());
                assertThat(page.items()).allSatisfy(item -> assertThat(expected).contains(item.caseId()));
                all.add(Map.of(
                        "profile",
                        profile,
                        "sql_count",
                        probe.rows.size(),
                        "statements",
                        List.copyOf(probe.rows),
                        "projection",
                        page));
            }
            String output = System.getProperty("resolveflow.d4.workspace");
            if (output != null) {
                Path path = Path.of(output);
                Files.createDirectories(path.getParent());
                Files.writeString(path, new ObjectMapper().writeValueAsString(all), StandardOpenOption.CREATE_NEW);
            }
        } finally {
            probe.active = false;
        }
    }

    @AfterEach
    void cleanOnlyOwnWorkspaceFixture() {
        jdbc.update(
                "DELETE FROM case_requested_action WHERE case_id IN (SELECT case_id FROM aftersale_case WHERE merchant_id IN ('D4-WS1','D4-WS2'))");
        jdbc.update("DELETE FROM aftersale_case WHERE merchant_id IN ('D4-WS1','D4-WS2')");
    }

    static boolean previousItem(ReviewQueueService.Page previous, ReviewQueueService.ReviewQueueItem item) {
        return previous.items().stream().anyMatch(old -> old.caseId().equals(item.caseId()));
    }
}
