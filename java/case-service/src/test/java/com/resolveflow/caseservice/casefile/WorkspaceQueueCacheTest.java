package com.resolveflow.caseservice.casefile;

import static org.assertj.core.api.Assertions.*;
import static org.mockito.ArgumentMatchers.*;
import static org.mockito.Mockito.*;

import com.resolveflow.shared.security.AuthenticatedPrincipal;
import com.resolveflow.shared.security.Role;
import io.micrometer.core.instrument.simple.SimpleMeterRegistry;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.Optional;
import org.junit.jupiter.api.Test;

class WorkspaceQueueCacheTest {
    private final CaseRepository repository = mock(CaseRepository.class);
    private final ReviewQueueCache cache = mock(ReviewQueueCache.class);
    private final SimpleMeterRegistry metrics = new SimpleMeterRegistry();
    private final ReviewQueueService service = new ReviewQueueService(repository, cache, metrics, true);
    private final AuthenticatedPrincipal staff = new AuthenticatedPrincipal("admin01", "M-1001", Role.REVIEWER, null);

    @Test
    void actualWorkspaceRequestHitsCacheAndAvoidsBothQueries() {
        Map<String, ReviewQueueService.Page> entries = new HashMap<>();
        when(cache.find(anyString(), any(), anyInt()))
                .thenAnswer(i -> Optional.ofNullable(entries.get(i.getArgument(1))));
        doAnswer(i -> {
                    entries.put(i.getArgument(1), i.getArgument(3));
                    return null;
                })
                .when(cache)
                .store(anyString(), any(), anyInt(), any());
        var first = service.workspace(staff, null, 20, "REVIEW", "", "PUBLIC");
        assertThat(service.workspace(staff, null, 20, "REVIEW", "  ", "PUBLIC")).isEqualTo(first);
        verify(repository, times(1)).countWorkspaceCases("M-1001", "admin01", "");
        verify(repository, times(1))
                .findOwnedWorkspaceCases(
                        eq("M-1001"), eq("admin01"), anyList(), eq("PUBLIC"), eq(""), isNull(), isNull(), eq(21));
        assertThat(metrics.get("resolveflow.review.cache")
                        .tag("outcome", "hit")
                        .counter()
                        .count())
                .isEqualTo(1);
    }

    @Test
    void cacheKeysSeparateMerchantPersonStageScopeAndSearch() {
        when(cache.find(anyString(), any(), anyInt())).thenReturn(Optional.empty());
        service.workspace(staff, null, 20, "REVIEW", "", "PUBLIC");
        service.workspace(
                new AuthenticatedPrincipal("admin02", "M-1001", Role.REVIEWER, null), null, 20, "REVIEW", "", "PUBLIC");
        service.workspace(staff, null, 20, "REVIEW", "", "MINE");
        service.workspace(staff, null, 20, "ALL", "", "PUBLIC");
        service.workspace(staff, null, 20, "REVIEW", "order", "PUBLIC");
        service.workspace(
                new AuthenticatedPrincipal("admin01", "M-1002", Role.REVIEWER, null), null, 20, "REVIEW", "", "PUBLIC");
        var keys = org.mockito.ArgumentCaptor.forClass(String.class);
        verify(cache, times(6)).find(anyString(), keys.capture(), eq(20));
        assertThat(keys.getAllValues()).doesNotHaveDuplicates();
    }

    @Test
    void invalidCursorAndBuyerAreRefusedBeforeCacheAccess() {
        assertThatThrownBy(() -> service.workspace(staff, "invalid", 20, "REVIEW", "", "PUBLIC"))
                .isInstanceOf(ReviewQueueCursor.InvalidCursorException.class);
        assertThatThrownBy(() -> service.workspace(
                        new AuthenticatedPrincipal("buyer", "M-1001", Role.CUSTOMER, "C-1"),
                        null,
                        20,
                        "REVIEW",
                        "",
                        "PUBLIC"))
                .isInstanceOf(RuntimeException.class);
        verifyNoInteractions(cache, repository);
    }

    @Test
    void cacheReadAndWriteFailureStillReturnsDatabaseFacts() {
        when(cache.find(anyString(), any(), anyInt())).thenThrow(new IllegalStateException("offline"));
        doThrow(new IllegalStateException("offline")).when(cache).store(anyString(), any(), anyInt(), any());
        assertThat(service.workspace(staff, null, 20, "REVIEW", "", "PUBLIC").items())
                .isEqualTo(List.of());
        verify(repository).countWorkspaceCases("M-1001", "admin01", "");
        assertThat(metrics.get("resolveflow.review.cache")
                        .tag("outcome", "error")
                        .counter()
                        .count())
                .isEqualTo(1);
    }

    @Test
    void cacheIoDoesNotOpenDatabaseTransaction() {
        var manager = new org.springframework.transaction.support.AbstractPlatformTransactionManager() {
            protected Object doGetTransaction() {
                return new Object();
            }

            protected void doBegin(Object t, org.springframework.transaction.TransactionDefinition d) {}

            protected void doCommit(org.springframework.transaction.support.DefaultTransactionStatus s) {}

            protected void doRollback(org.springframework.transaction.support.DefaultTransactionStatus s) {}
        };
        var production = new ReviewQueueService(repository, cache, metrics, true, manager);
        when(cache.find(anyString(), any(), anyInt()))
                .thenAnswer(i -> {
                    assertThat(org.springframework.transaction.support.TransactionSynchronizationManager
                                    .isActualTransactionActive())
                            .isFalse();
                    return Optional.empty();
                });
        when(repository.countWorkspaceCases(anyString(), anyString(), anyString()))
                .thenAnswer(i -> {
                    assertThat(org.springframework.transaction.support.TransactionSynchronizationManager
                                    .isActualTransactionActive())
                            .isTrue();
                    assertThat(org.springframework.transaction.support.TransactionSynchronizationManager
                                    .isCurrentTransactionReadOnly())
                            .isTrue();
                    return List.of();
                });
        doAnswer(i -> {
                    assertThat(org.springframework.transaction.support.TransactionSynchronizationManager
                                    .isActualTransactionActive())
                            .isFalse();
                    return null;
                })
                .when(cache)
                .store(anyString(), any(), anyInt(), any());
        production.workspace(staff, null, 20, "REVIEW", "", "PUBLIC");
    }
}
