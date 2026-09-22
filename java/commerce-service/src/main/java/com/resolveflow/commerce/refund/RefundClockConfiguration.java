package com.resolveflow.commerce.refund;

import java.time.Clock;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;

/**
 * The clock the refund path reads time from.
 *
 * <p>A bean rather than {@code Instant.now()} at each call site: the refund path records when a
 * reservation was made, when it settled and when to retry, and a test that wants to ask "what happens after
 * the retry window" must be able to move that time without waiting for it (docs/engineering.md:9 — Clock
 * injectable).
 *
 * <p>One clock for the whole service rather than one per component: two clocks would let one operation's
 * {@code reserved_at} and its {@code settled_at} disagree about what "now" is, which is not a question this
 * service should have an opinion about.
 */
@Configuration
public class RefundClockConfiguration {

    @Bean
    Clock refundClock() {
        return Clock.systemUTC();
    }
}
