package com.resolveflow.commerce.messaging;

import java.nio.charset.StandardCharsets;
import org.apache.rocketmq.client.consumer.DefaultMQPushConsumer;
import org.apache.rocketmq.client.consumer.listener.ConsumeConcurrentlyStatus;
import org.apache.rocketmq.client.consumer.listener.MessageListenerConcurrently;
import org.apache.rocketmq.client.exception.MQClientException;
import org.apache.rocketmq.common.consumer.ConsumeFromWhere;
import org.apache.rocketmq.common.message.MessageExt;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.context.SmartLifecycle;
import org.springframework.stereotype.Component;

/**
 * The RocketMQ consumer that feeds {@link RefundCommandConsumer} (C05.1b).
 *
 * <p>It is wired by configuration rather than by an annotation processor: the listener here does one thing —
 * hand the raw bytes to the consumer — and everything about whether the message is acceptable, whether it was
 * seen before and what applying it means lives in the consumer, where it can be tested without a broker.
 *
 * <p><b>Acknowledgement is the interesting decision.</b> The transport is told "consumed" only when the
 * consumer either applied the command or recognised it as a duplicate:
 *
 * <ul>
 *   <li>a redelivery is acknowledged, because it is already applied and asking for it again forever would
 *       block the queue;
 *   <li>a <em>refusal</em> is acknowledged too, deliberately: the message will never become valid — it is signed
 *       by an unknown key, or its signature is broken — so retrying it is a loop that never ends. The refusal is
 *       recorded in {@code event_rejection} instead, which is where an operator looks
 *       (docs/engineering.md:56 — 毒消息最终DLQ，需要操作台可追踪);
 *   <li>anything else — a database that is down, a lock timeout — is <em>not</em> acknowledged, so the broker
 *       redelivers. That is the at-least-once half of the contract, and the inbox is what makes it safe.
 * </ul>
 */
@Component
@ConditionalOnProperty(name = "resolveflow.events.consumer.enabled", havingValue = "true")
public class RefundCommandListener implements SmartLifecycle {

    private static final Logger LOG = LoggerFactory.getLogger(RefundCommandListener.class);

    private final RefundCommandConsumer consumer;
    private final String namesrv;
    private final String topic;
    private final String group;
    private DefaultMQPushConsumer pushConsumer;

    public RefundCommandListener(
            RefundCommandConsumer consumer,
            @Value("${resolveflow.events.namesrv:127.0.0.1:9876}") String namesrv,
            @Value("${resolveflow.events.topics.case:rf.case.core.v2}") String topic,
            @Value("${resolveflow.events.consumer.group:commerce-refund-command}") String group) {
        this.consumer = consumer;
        this.namesrv = namesrv;
        this.topic = topic;
        this.group = group;
    }

    @Override
    public void start() {
        DefaultMQPushConsumer candidate = new DefaultMQPushConsumer(group);
        candidate.setNamesrvAddr(namesrv);
        // ConsumeFromWhere.FIRST is wrong for money: replaying a topic's whole history on every restart would
        // re-apply old commands through the inbox (harmless, but pointless work). LAST_OFFSET means the broker's
        // own progress decides, and the inbox covers whatever it redelivers.
        candidate.setConsumeFromWhere(ConsumeFromWhere.CONSUME_FROM_LAST_OFFSET);
        try {
            candidate.subscribe(topic, "*");
            candidate.registerMessageListener((MessageListenerConcurrently) (messages, context) -> handle(messages));
            candidate.start();
        } catch (MQClientException cannotStart) {
            // Starting is failed loudly rather than swallowed: a consumer that is not listening would leave
            // commands unapplied while the service looked healthy.
            LOG.error("the refund command listener could not start against {}", namesrv, cannotStart);
            throw new IllegalStateException("refund command listener did not start", cannotStart);
        }
        this.pushConsumer = candidate;
        LOG.info("listening on {} for core events (group {})", topic, group);
    }

    private ConsumeConcurrentlyStatus handle(java.util.List<MessageExt> messages) {
        for (MessageExt message : messages) {
            String body = new String(message.getBody(), StandardCharsets.UTF_8);
            try {
                RefundCommandConsumer.Disposition disposition = consumer.consume(body);
                LOG.debug("core event {} -> {}", message.getMsgId(), disposition);
            } catch (EventVerifier.RefusedEventException refused) {
                // Terminal, and already recorded. Acknowledging stops a broken message from blocking the queue;
                // the rejection row is what keeps it visible.
                LOG.warn("core event {} refused: {}", message.getMsgId(), refused.refusal());
            } catch (RuntimeException transientFailure) {
                // Not acknowledged: the broker redelivers, and the inbox makes the second attempt safe.
                LOG.warn(
                        "core event {} could not be applied yet; asking for redelivery",
                        message.getMsgId(),
                        transientFailure);
                return ConsumeConcurrentlyStatus.RECONSUME_LATER;
            }
        }
        return ConsumeConcurrentlyStatus.CONSUME_SUCCESS;
    }

    @Override
    public void stop() {
        if (pushConsumer != null) {
            pushConsumer.shutdown();
            pushConsumer = null;
        }
    }

    @Override
    public boolean isRunning() {
        return pushConsumer != null;
    }
}
