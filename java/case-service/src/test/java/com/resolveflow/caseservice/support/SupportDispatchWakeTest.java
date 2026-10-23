package com.resolveflow.caseservice.support;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.Mockito.*;

import java.util.concurrent.CountDownLatch;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicInteger;
import org.junit.jupiter.api.Test;

class SupportDispatchWakeTest {
    @Test
    void committedInputWakesExistingWorkerAndAnInputArrivingDuringWorkIsNotLost() throws Exception {
        var turns = mock(SupportAgentTurns.class);
        var first = new CountDownLatch(1);
        var release = new CountDownLatch(1);
        var second = new CountDownLatch(1);
        var calls = new AtomicInteger();
        doAnswer(call -> {
                    assertThat(Thread.currentThread().getName()).isEqualTo("support-agent-dispatch");
                    if (calls.incrementAndGet() == 1) {
                        first.countDown();
                        assertThat(release.await(2, TimeUnit.SECONDS)).isTrue();
                    } else second.countDown();
                    return null;
                })
                .when(turns)
                .dispatchOne();
        var loop = new SupportAgentDispatchLoop(turns);
        try {
            loop.queued(new SupportAgentTurns.Queued());
            assertThat(first.await(2, TimeUnit.SECONDS)).isTrue();
            loop.queued(new SupportAgentTurns.Queued());
            release.countDown();
            assertThat(second.await(2, TimeUnit.SECONDS)).isTrue();
        } finally {
            release.countDown();
            loop.close();
        }
        verify(turns, times(2)).dispatchOne();
    }
}
