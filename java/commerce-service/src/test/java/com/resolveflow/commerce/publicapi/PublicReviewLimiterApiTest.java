package com.resolveflow.commerce.publicapi;

import static org.mockito.Mockito.*;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.*;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.*;

import com.resolveflow.commerce.catalog.ProductReviewService;
import com.resolveflow.shared.security.IdentityAccessWire.*;
import com.resolveflow.shared.security.Role;
import java.util.List;
import org.junit.jupiter.api.Test;
import org.springframework.http.MediaType;
import org.springframework.test.web.servlet.setup.MockMvcBuilders;

class PublicReviewLimiterApiTest {
    @Test
    void limitedAndUnavailableRedisBothPreventReviewWritesWithRetryHeaders() throws Exception {
        for (RuntimeException error :
                List.of(new ReviewWriteLimiter.WriteLimited(), new ReviewWriteLimiter.WriteUnavailable())) {
            var access = mock(CommerceAccess.class);
            var reviews = mock(ProductReviewService.class);
            var limiter = mock(ReviewWriteLimiter.class);
            var actor = new Context(
                    "buyer", null, Role.CUSTOMER, "B-1", 1, List.of(new Binding("M-1", "B-1", "store")), null);
            when(access.buyer("Bearer user")).thenReturn(actor);
            doThrow(error).when(limiter).check(actor.principal(), ReviewWriteLimiter.Action.WRITE);
            var mvc = MockMvcBuilders.standaloneSetup(new PublicReviewController(access, reviews, limiter))
                    .setControllerAdvice(new PublicCommerceErrors())
                    .build();
            boolean limited = error instanceof ReviewWriteLimiter.WriteLimited;
            mvc.perform(post("/api/v1/shop/orders/lines/L-1/review")
                            .header("Authorization", "Bearer user")
                            .contentType(MediaType.APPLICATION_JSON)
                            .content("{\"rating\":5,\"body\":\"test\",\"expected_version\":0}"))
                    .andExpect(status().is(limited ? 429 : 503))
                    .andExpect(header().string("Retry-After", limited ? "60" : "1"));
            verifyNoInteractions(reviews);
        }
    }
}
