package com.resolveflow.caseservice.outbox;

import org.springframework.boot.autoconfigure.condition.ConditionalOnMissingBean;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;

/**
 * How this service hands a signed event to the transport.
 *
 * <p>The default publisher is {@link NoTransportConfigured}, which refuses everything. That is a deliberate
 * choice over a silent no-op: a service whose broker is not wired must not look like it delivered anything.
 * An outbox whose events quietly disappeared would make every "at least once" claim false while every test
 * that only checked the writer still passed.
 *
 * <p>C05 adds the RocketMQ publisher; until it is configured, this service's events accumulate as PENDING and
 * say so. A deployment (or a test) supplies its own bean and this one steps aside.
 */
@Configuration
public class OutboxConfiguration {

    /** A publisher for a deployment that has no broker: it refuses, loudly, and the outbox retries then ages. */
    static final class NoTransportConfigured implements EventPublisher {

        @Override
        public void publish(String topic, String envelope, String eventId) {
            throw new PublishException(
                    "no event transport is configured for this service; " + eventId + " was not published to " + topic);
        }
    }

    @Bean
    @ConditionalOnMissingBean(EventPublisher.class)
    EventPublisher noTransportConfigured() {
        return new NoTransportConfigured();
    }
}
