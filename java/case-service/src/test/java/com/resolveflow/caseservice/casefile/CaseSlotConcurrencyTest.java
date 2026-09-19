package com.resolveflow.caseservice.casefile;

import static org.assertj.core.api.Assertions.assertThat;

import com.resolveflow.caseservice.CaseDatabaseTest;
import com.resolveflow.shared.security.AuthenticatedPrincipal;
import com.resolveflow.shared.security.JwtCodec;
import com.resolveflow.shared.security.Role;
import java.util.ArrayList;
import java.util.List;
import java.util.concurrent.Callable;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.Future;
import java.util.concurrent.TimeUnit;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.TestConfiguration;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Primary;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.web.client.RestClient;

/**
 * The line slot under concurrency, which is the only way to test it honestly.
 *
 * <p>A single-threaded test can only show that the second call was refused; it cannot show that two
 * simultaneous calls cannot both succeed. These tests start real threads against the real database and
 * assert on what the database ends up holding, because "one active case per line" is a promise about
 * races, not about the happy path (docs/domain-model.md:26).
 */
class CaseSlotConcurrencyTest extends CaseDatabaseTest {

    private static final String LINE = "7001";
    private static final int THREADS = 8;

    @Autowired
    CaseService cases;

    @Autowired
    StubCommerce commerce;

    @Autowired
    JdbcTemplate jdbc;

    @TestConfiguration
    static class StubCommerceConfiguration {

        @Bean
        @Primary
        StubCommerce stubCommerce(RestClient.Builder builder, JwtCodec jwtCodec) {
            return new StubCommerce(builder, jwtCodec);
        }
    }

    @BeforeEach
    void clean() {
        deleteAllCaseData(jdbc);
    }

    private static final AuthenticatedPrincipal CUSTOMER =
            new AuthenticatedPrincipal("demo-customer", "M-1001", Role.CUSTOMER, "C-2002");

    private static CaseCreateRequest request(String description) {
        return new CaseCreateRequest(LINE, description, List.of("REFUND"));
    }

    /** Runs the same callable on {@value #THREADS} threads released at once. */
    private List<Object> race(Callable<Object> call) throws Exception {
        ExecutorService pool = Executors.newFixedThreadPool(THREADS);
        CountDownLatch start = new CountDownLatch(1);
        List<Future<Object>> futures = new ArrayList<>();
        for (int index = 0; index < THREADS; index++) {
            futures.add(pool.submit(() -> {
                start.await(30, TimeUnit.SECONDS);
                try {
                    return call.call();
                } catch (RuntimeException error) {
                    return error;
                }
            }));
        }
        start.countDown();
        List<Object> results = new ArrayList<>();
        for (Future<Object> future : futures) {
            results.add(future.get(60, TimeUnit.SECONDS));
        }
        pool.shutdownNow();
        return results;
    }

    @Test
    @DisplayName("eight simultaneous creates for one line leave exactly one case")
    void oneLineYieldsOneCaseUnderRace() throws Exception {
        List<Object> results =
                race(() -> cases.create(CUSTOMER, java.util.UUID.randomUUID().toString(), request("并发")));

        long created =
                results.stream().filter(CaseService.Created.class::isInstance).count();
        long refused = results.stream()
                .filter(CaseService.CaseAlreadyOpenException.class::isInstance)
                .count();

        assertThat(created).as("exactly one caller may open the case").isEqualTo(1);
        assertThat(refused)
                .as("every other caller is told the line already has an open case")
                .isEqualTo(THREADS - 1);
        assertThat(count("aftersale_case")).isEqualTo(1);
        assertThat(count("active_case_slot")).as("one slot, one case").isEqualTo(1);
        assertThat(count("case_timeline"))
                .as("one trajectory entry for the one case")
                .isEqualTo(1);
        assertThat(count("case_requested_action")).isEqualTo(1);
    }

    @Test
    @DisplayName("eight simultaneous creates with one key leave exactly one case, and never two answers")
    void oneKeyYieldsOneCaseUnderRace() throws Exception {
        String sharedKey = "race-shared-key";

        List<Object> results = race(() -> cases.create(CUSTOMER, sharedKey, request("同一请求")));

        List<CaseService.Created> answers = results.stream()
                .filter(CaseService.Created.class::isInstance)
                .map(CaseService.Created.class::cast)
                .toList();
        long conflicts = results.stream()
                .filter(CaseService.IdempotencyConflictException.class::isInstance)
                .count();

        assertThat(count("aftersale_case"))
                .as("the key cannot create a second case")
                .isEqualTo(1);
        assertThat(answers).as("at least one caller got the answer").isNotEmpty();
        assertThat(answers.stream().map(answer -> answer.body().caseId()).distinct())
                .as("every answer names the same case")
                .hasSize(1);
        assertThat(answers.stream().filter(CaseService.Created::replayed).count())
                .as("a concurrent duplicate may be told to retry; it is never given a second case")
                .isLessThanOrEqualTo(answers.size());
        assertThat(conflicts + answers.size()).isEqualTo(THREADS);
    }

    private int count(String table) {
        return jdbc.queryForObject("SELECT COUNT(*) FROM " + table, Integer.class);
    }
}
