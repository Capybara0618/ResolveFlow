package com.resolveflow.commerce.messaging;

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
 * Handing a signed result envelope to RocketMQ (C05.2b).
 *
 * <p>The mirror of the case side's publisher (C05.1b), and the same two decisions: what counts as success is
 * exactly {@code SEND_OK} (anything else is a {@link PublishException} and the outbox keeps the row), and the
 * producer is a lifecycle bean rather than something started in a constructor — starting is a network call, and
 * a broker that is not up yet must show up as results ageing in the outbox, not as a service that cannot boot.
 *
 * <p>Off unless asked for, like every other transport switch in this project: a service started without it
 * still settles refunds and still records the results it owes, and simply has not handed them over yet.
 */
@Component
@ConditionalOnProperty(name = "resolveflow.events.publisher.enabled", havingValue = "true")
public class RocketMqResultPublisher implements EventPublisher, SmartLifecycle {

    private static final Logger LOG = LoggerFactory.getLogger(RocketMqResultPublisher.class);

    private final String namesrv;
    private final String producerGroup;
    private DefaultMQProducer producer;

    public RocketMqResultPublisher(
            @Value("${resolveflow.events.namesrv:127.0.0.1:9876}") String namesrv,
            @Value("${resolveflow.events.producer.group:commerce-service-outbox}") String producerGroup) {
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
            LOG.error("the result publisher could not start against {}", namesrv, cannotStart);
            throw new IllegalStateException("result publisher did not start", cannotStart);
        }
        this.producer = candidate;
        LOG.info("publishing core results to {}", namesrv);
    }

    @Override
    public void publish(String topic, String envelope, String eventId) {
        if (producer == null) {
            throw new PublishException("the result publisher is not running");
        }
        try {
            // The document's topic is the protocol's (rf.commerce.core.v2) and the signature covers it; the name
            // handed to RocketMQ is derived from it, because the broker refuses dots outright (C05.1c,
            // docs/compatibility-report.md 5.12). The two are related in exactly one place, shared with the case
            // side so the two directions cannot disagree about it.
            Message message = new Message(CoreTopicNames.brokerName(topic), envelope.getBytes(StandardCharsets.UTF_8));
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
