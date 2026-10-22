package com.resolveflow.commerce.catalog;

import static org.assertj.core.api.Assertions.*;
import static org.mockito.Mockito.*;

import org.junit.jupiter.api.Test;

class CheckoutRecoveryLoopTest {
    @Test
    void failedPassDoesNotStopFutureTicksAndBatchIsBounded() {
        var recovery = mock(CheckoutRecoveryService.class);
        when(recovery.tick(20))
                .thenThrow(new IllegalStateException("temporary"))
                .thenReturn(new CheckoutRecoveryService.Pass(0, 1, 1, 0));
        var loop = new CheckoutRecoveryLoop(recovery, 20);
        assertThatCode(loop::tick).doesNotThrowAnyException();
        loop.tick();
        verify(recovery, times(2)).tick(20);
        assertThatThrownBy(() -> new CheckoutRecoveryLoop(recovery, 101)).isInstanceOf(IllegalArgumentException.class);
    }
}
