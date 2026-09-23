package com.resolveflow.caseservice.outbox;

import com.resolveflow.shared.core.CoreTopicNames;
import java.nio.charset.StandardCharsets;
import org.apache.rocketmq.client.exception.MQClientException;
import org.apache.rocketmq.client.producer.DefaultMQProducer;
import org.apache.rocketmq.client.producer.SendResult;
import org.apache.rocketmq.client.producer.SendStatus;
import org.apache.rocketmq.common.message.Message;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.context.SmartLifecycle;
import org.springframework.stereotype.Component;

/**
 * Handing a signed envelope to RocketMQ (C05.1b).
 *
 * <p>What counts as success is deliberately narrow: the broker returned {@code SEND_OK}. Anything else — a
 * timeout, a full queue, a {@code FLUSH_DISK_TIMEOUT} — is a {@link PublishException}, and the outbox keeps the
 * row and tries again. A producer that treated "the call returned" as "the message is delivered" would drop
 * events during exactly the broker trouble the outbox exists to survive.
 *
 * <p>The producer is a lifecycle bean rather than a {@code @Bean} that starts in its constructor: starting is a
 * network call, and doing it during context refresh turns a broker that is simply not up yet into a service that
 * cannot start at all. Its absence must show up as events ageing in the outbox, not as a crash loop.
 */
@Component
@ConditionalOnProperty(name = "resolveflow.events.publisher.enabled", havingValue = "true")
public class RocketMqEventPublisher implements EventPublisher, SmartLifecycle {

    private static final Logger LOG = LoggerFactory.getLogger(RocketMqEventPublisher.class);

    private final String namesrv;
    private final String producerGroup;
    private DefaultMQProducer producer;

    public RocketMqEventPublisher(
            @Value("${resolveflow.events.namesrv:127.0.0.1:9876}") String namesrv,
            @Value("${resolveflow.events.producer.group:case-service-outbox}") String producerGroup) {
        this.namesrv = namesrv;
        this.producerGroup = producerGroup;
    }

    @Override
    public void start() {
        DefaultMQProducer candidate = new DefaultMQProducer(producerGroup);
        candidate.setNamesrvAddr(namesrv);
        candidate.setSendMsgTimeout(3000);
        try {
            candidate.start();
        } catch (MQClientException cannotStart) {
            LOG.error("the outbox publisher could not start against {}", namesrv, cannotStart);
            throw new IllegalStateException("outbox publisher did not start", cannotStart);
        }
        this.producer = candidate;
        LOG.info("publishing core events to {}", namesrv);
    }

    @Override
    public void publish(String topic, String envelope, String eventId) {
        if (producer == null) {
            throw new PublishException("the outbox publisher is not running");
        }
        try {
            // The document's topic is the protocol's (rf.case.core.v2) and the signature covers it; the name
            // handed to RocketMQ is derived from it, because the broker refuses dots outright (C05.1c,
            // docs/compatibility-report.md 5.12). The two are related in exactly one place.
            Message message = new Message(CoreTopicNames.brokerName(topic), envelope.getBytes(StandardCharsets.UTF_8));
            // The keys are the event id, so an operator can find one event in the broker's own tooling.
            message.setKeys(eventId);
            SendResult result = producer.send(message);
            if (!SendStatus.SEND_OK.equals(result.getSendStatus())) {
                throw new PublishException("broker answered " + result.getSendStatus() + " for " + eventId);
            }
        } catch (PublishException refused) {
            throw refused;
        } catch (Exception failed) {
            throw new PublishException("publishing " + eventId + " failed: " + failed.getMessage(), failed);
        }
    }

    @Override
    public void stop() {
        if (producer != null) {
            producer.shutdown();
            producer = null;
        }
    }

    @Override
    public boolean isRunning() {
        return producer != null;
    }
}
