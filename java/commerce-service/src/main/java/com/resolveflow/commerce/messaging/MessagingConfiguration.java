package com.resolveflow.commerce.messaging;

import org.springframework.boot.autoconfigure.condition.ConditionalOnMissingBean;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;

/**
 * How this service hands a signed result to the transport.
 *
 * <p>The default publisher is {@link NoTransportConfigured}, which refuses everything — the same choice the case
 * side makes (C05.1b), for the same reason: a service whose broker is not wired must not look like it delivered
 * anything. An outbox whose results quietly disappeared would make every "at least once" claim false while every
 * test that only checked the writer still passed.
 *
 * <p>Without it the delivery service has no publisher to inject and the service cannot start at all, which is
 * the other wrong answer: settling refunds must not depend on a broker being configured. With it, a broker-less
 * commerce keeps settling refunds, keeps recording the outcomes it owes, and those rows age in the outbox and
 * say why — a fact an operator can see and a manual replay can start from.
 */
@Configuration
public class MessagingConfiguration {

    /** A publisher for a deployment that has no broker: it refuses, loudly, and the outbox retries then ages. */
    static final class NoTransportConfigured implements EventPublisher {

        @Override
        public void publish(String topic, String envelope, String eventId) {
            throw new PublishException("no result transport is configured for this service; " + eventId
                    + " was not published to " + topic);
        }
    }

    @Bean
    @ConditionalOnMissingBean(EventPublisher.class)
    EventPublisher noTransportConfigured() {
        return new NoTransportConfigured();
    }
}
