package com.resolveflow.commerce.catalog;

import static org.assertj.core.api.Assertions.*;
import static org.mockito.ArgumentMatchers.*;
import static org.mockito.Mockito.*;

import com.resolveflow.shared.shopping.ProductReviewWire.*;
import io.micrometer.core.instrument.simple.SimpleMeterRegistry;
import java.util.List;
import org.junit.jupiter.api.Test;
import org.springframework.data.redis.core.StringRedisTemplate;
import tools.jackson.databind.ObjectMapper;

class ProductReviewReadCacheTest {
    @Test
    void databaseFallbackIsBoundedWhenCacheIsUnavailable() throws Exception {
        var service = mock(ProductReviewService.class);
        var redis = mock(StringRedisTemplate.class);
        var metrics = new SimpleMeterRegistry();
        var cache = new ProductReviewReadCache(service, redis, new ObjectMapper(), metrics, false);
        var page = new Page(List.of(), new Summary(0, null, List.of(0L, 0L, 0L, 0L, 0L)), null);
        var reading = new java.util.concurrent.CountDownLatch(8);
        var release = new java.util.concurrent.CountDownLatch(1);
        when(service.publicPage("P-1", null, 10)).thenAnswer(i -> {
            reading.countDown();
            if (!release.await(5, java.util.concurrent.TimeUnit.SECONDS)) throw new AssertionError("fixture timed out");
            return page;
        });
        var pool = java.util.concurrent.Executors.newFixedThreadPool(12);
        var start = new java.util.concurrent.CountDownLatch(1);
        try {
            var futures = java.util.stream.IntStream.range(0, 12)
                    .mapToObj(i -> pool.submit(() -> {
                        start.await();
                        try {
                            cache.read("P-1", null, 10);
                            return true;
                        } catch (ProductReviewReadCache.ReadBusy busy) {
                            return false;
                        }
                    }))
                    .toList();
            start.countDown();
            assertThat(reading.await(2, java.util.concurrent.TimeUnit.SECONDS)).isTrue();
            Thread.sleep(250);
            release.countDown();
            int accepted = 0;
            for (var f : futures) if (f.get(2, java.util.concurrent.TimeUnit.SECONDS)) accepted++;
            assertThat(accepted).isEqualTo(8);
            assertThat(metrics.counter("resolveflow.product_reviews.fallback", "outcome", "rejected")
                            .count())
                    .isEqualTo(4);
        } finally {
            release.countDown();
            pool.shutdownNow();
        }
    }

    @Test
    void firstPageCacheHitStillChecksAuthoritativeEpochButSkipsHeavySnapshot() {
        var service = mock(ProductReviewService.class);
        var redis = mock(StringRedisTemplate.class, RETURNS_DEEP_STUBS);
        var page = new Page(List.of(), new Summary(0, null, List.of(0L, 0L, 0L, 0L, 0L)), null);
        when(service.publicEpoch("P-1")).thenReturn(4L);
        when(redis.opsForValue().get(anyString())).thenReturn(new ObjectMapper().writeValueAsString(page));
        var cache = new ProductReviewReadCache(service, redis, new ObjectMapper(), new SimpleMeterRegistry(), true);
        assertThat(cache.read("P-1", null, 10)).isEqualTo(page);
        verify(service).publicEpoch("P-1");
        verify(service, never()).publicPage(anyString(), any(), any());
    }

    @Test
    void redisFailureFallsBackWithoutChangingAuthorityAndInvalidPagingDoesNotReadRedis() {
        var service = mock(ProductReviewService.class);
        var redis = mock(StringRedisTemplate.class, RETURNS_DEEP_STUBS);
        var page = new Page(List.of(), new Summary(0, null, List.of(0L, 0L, 0L, 0L, 0L)), null);
        when(service.publicEpoch("P-1")).thenReturn(1L);
        when(service.publicPage("P-1", null, 10)).thenReturn(page);
        when(redis.opsForValue().get(anyString())).thenThrow(new IllegalStateException("offline"));
        var cache = new ProductReviewReadCache(service, redis, new ObjectMapper(), new SimpleMeterRegistry(), true);
        assertThat(cache.read("P-1", null, 10)).isEqualTo(page);
        assertThatThrownBy(() -> cache.read("P-1", null, 21)).isInstanceOf(IllegalArgumentException.class);
        verify(service, times(1)).publicEpoch("P-1");
    }
}
