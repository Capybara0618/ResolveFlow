package com.resolveflow.caseservice.casefile;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyInt;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.when;

import com.resolveflow.caseservice.error.ApiExceptionHandler;
import com.resolveflow.shared.security.AuthenticatedPrincipal;
import com.resolveflow.shared.security.Role;
import io.micrometer.core.instrument.simple.SimpleMeterRegistry;
import java.util.List;
import java.util.concurrent.Callable;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.Future;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicInteger;
import org.junit.jupiter.api.Test;
import org.springframework.http.HttpStatus;

class ReviewQueueBackpressureTest {

    @Test
    void rejectedFallbackMapsToRetryableServiceUnavailable() {
        var response =
                new ApiExceptionHandler().reviewQueueBusy(new ReviewQueueService.ReviewQueueBusyException(), null);
        assertThat(response.getStatusCode()).isEqualTo(HttpStatus.SERVICE_UNAVAILABLE);
        assertThat(response.getBody()).isNotNull();
        assertThat(response.getBody().code()).isEqualTo("SERVICE_UNAVAILABLE");
        assertThat(response.getBody().retryable()).isTrue();
    }

    @Test
    void redisOutageAdmitsAtMostEightDatabaseReadsAndRejectsExcess() throws Exception {
        CaseRepository repository = mock(CaseRepository.class);
        ReviewQueueCache cache = mock(ReviewQueueCache.class);
        when(cache.find("M-1001", null, 20)).thenThrow(new IllegalStateException("redis disconnected"));
        CountDownLatch reading = new CountDownLatch(8);
        CountDownLatch release = new CountDownLatch(1);
        AtomicInteger active = new AtomicInteger();
        AtomicInteger peak = new AtomicInteger();
        when(repository.findReviewQueue(eq("M-1001"), any(), any(), anyInt())).thenAnswer(invocation -> {
            int current = active.incrementAndGet();
            peak.accumulateAndGet(current, Math::max);
            reading.countDown();
            try {
                if (!release.await(5, TimeUnit.SECONDS)) {
                    throw new AssertionError("database fixture timed out");
                }
                return List.of();
            } finally {
                active.decrementAndGet();
            }
        });
        SimpleMeterRegistry metrics = new SimpleMeterRegistry();
        ReviewQueueService service = new ReviewQueueService(repository, cache, metrics, true);
        AuthenticatedPrincipal staff = new AuthenticatedPrincipal("staff", "M-1001", Role.REVIEWER, null);
        ExecutorService pool = Executors.newFixedThreadPool(12);
        CountDownLatch start = new CountDownLatch(1);
        try {
            List<Future<Boolean>> results = java.util.stream.IntStream.range(0, 12)
                    .<Callable<Boolean>>mapToObj(i -> () -> {
                        start.await();
                        try {
                            service.list(staff, null, null);
                            return true;
                        } catch (ReviewQueueService.ReviewQueueBusyException busy) {
                            return false;
                        }
                    })
                    .map(pool::submit)
                    .toList();
            start.countDown();
            assertThat(reading.await(2, TimeUnit.SECONDS)).isTrue();
            assertThat(metrics.get("resolveflow.review.database.inflight")
                            .gauge()
                            .value())
                    .isEqualTo(8);
            assertThat(metrics.get("resolveflow.review.database.peak").gauge().value())
                    .isEqualTo(8);
            Thread.sleep(250);
            release.countDown();
            int accepted = 0;
            for (Future<Boolean> result : results) {
                accepted += result.get(2, TimeUnit.SECONDS) ? 1 : 0;
            }
            assertThat(accepted).isEqualTo(8);
            assertThat(peak.get()).isEqualTo(8);
            assertThat(metrics.counter("resolveflow.review.fallback", "outcome", "rejected")
                            .count())
                    .isEqualTo(4);
            assertThat(active.get()).isZero();
            assertThat(metrics.get("resolveflow.review.database.inflight")
                            .gauge()
                            .value())
                    .isZero();
            assertThat(metrics.get("resolveflow.review.database.peak").gauge().value())
                    .isEqualTo(8);
            assertThat(service.list(staff, null, null).items()).isEmpty();
        } finally {
            release.countDown();
            pool.shutdownNow();
        }
    }
}
