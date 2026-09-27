package com.resolveflow.caseservice.casefile;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.verifyNoInteractions;
import static org.mockito.Mockito.when;

import com.resolveflow.shared.security.AuthenticatedPrincipal;
import com.resolveflow.shared.security.Role;
import io.micrometer.core.instrument.simple.SimpleMeterRegistry;
import java.util.List;
import java.util.Optional;
import org.junit.jupiter.api.Test;

class ReviewQueueCacheTest {

    @Test
    void cacheHitAvoidsDatabaseAndPreservesMerchantScope() {
        CaseRepository repository = mock(CaseRepository.class);
        ReviewQueueCache cache = mock(ReviewQueueCache.class);
        ReviewQueueService.Page page = new ReviewQueueService.Page(List.of(), null, 20);
        when(cache.find("M-1001", null, 20)).thenReturn(Optional.of(page));
        ReviewQueueService service = new ReviewQueueService(repository, cache, new SimpleMeterRegistry(), true);
        assertThat(service.list(new AuthenticatedPrincipal("staff", "M-1001", Role.REVIEWER, null), null, null))
                .isSameAs(page);
        verify(cache).find("M-1001", null, 20);
        verifyNoInteractions(repository);
    }

    @Test
    void customerCannotReadCacheAndMissFallsBackToScopedDatabase() {
        CaseRepository repository = mock(CaseRepository.class);
        ReviewQueueCache cache = mock(ReviewQueueCache.class);
        ReviewQueueService service = new ReviewQueueService(repository, cache, new SimpleMeterRegistry(), true);
        assertThatThrownBy(() ->
                        service.list(new AuthenticatedPrincipal("buyer", "M-1001", Role.CUSTOMER, "C-1"), null, null))
                .isInstanceOf(RuntimeException.class);
        verifyNoInteractions(cache, repository);

        when(cache.find("M-2002", null, 20)).thenReturn(Optional.empty());
        when(repository.findReviewQueue("M-2002", null, null, 21)).thenReturn(List.of());
        assertThat(service.list(new AuthenticatedPrincipal("staff", "M-2002", Role.REVIEWER, null), null, null)
                        .items())
                .isEmpty();
        verify(repository).findReviewQueue("M-2002", null, null, 21);
        verify(cache).store("M-2002", null, 20, new ReviewQueueService.Page(List.of(), null, 20));
    }
}
