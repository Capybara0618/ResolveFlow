package com.resolveflow.commerce.refund;

import java.time.Clock;
import java.time.Duration;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.http.client.SimpleClientHttpRequestFactory;
import org.springframework.web.client.RestClient;

/**
 * The clock the refund path reads time from, and the HTTP client it reaches the provider with.
 *
 * <p>A clock bean rather than {@code Instant.now()} at each call site: the refund path records when a
 * reservation was made, when it settled and when to retry, and a test that wants to ask "what happens after
 * the retry window" must be able to move that time without waiting for it (docs/engineering.md:9 — Clock
 * injectable). One clock for the whole service, because two would let an operation's {@code reserved_at} and
 * its {@code settled_at} disagree about what "now" is.
 *
 * <p>The provider client gets explicit timeouts. A provider that accepts a connection and then says nothing
 * is the case this path exists for: without a read timeout the dispatch would hang forever holding an
 * operation IN_PROGRESS, and "no answer" would never become {@code UNKNOWN}
 * (docs/domain-model.md:51 — 网络超时=UNKNOWN而非失败).
 */
@Configuration
public class RefundClockConfiguration {

    @Bean
    Clock refundClock() {
        return Clock.systemUTC();
    }

    /**
     * The client Commerce uses to call the outside world.
     *
     * <p>Its own builder rather than the shared one the internal surface uses: this one talks to a service
     * that is not ours, with a different base URL and its own timeouts, and sharing a builder would tie two
     * unrelated dependencies' settings together.
     */
    @Bean
    RestClient.Builder refundProviderRestClientBuilder() {
        SimpleClientHttpRequestFactory factory = new SimpleClientHttpRequestFactory();
        factory.setConnectTimeout(Duration.ofSeconds(2));
        // 5 seconds is longer than any local stub answers in and shorter than a human's patience for a
        // refund click. A timeout here becomes UNKNOWN, which is a state this path handles; a hang is not.
        factory.setReadTimeout(Duration.ofSeconds(5));
        return RestClient.builder().requestFactory(factory);
    }
}
