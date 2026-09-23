package com.resolveflow.caseservice.result;

import com.resolveflow.shared.core.CoreEnvelope;
import com.resolveflow.shared.core.CoreTopicNames;
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
 * The RocketMQ consumer that feeds {@link CaseResultConsumer} (C05.2c).
 *
 * <p>This is the last link of the refund chain. C05.2b built both ends of it — Commerce settles a refund and
 * writes a signed result into its own outbox (b-1), a delivery loop hands those bytes to the broker (b-2), and
 * this service can verify a result, claim it exactly once and project it onto the case (b-3a/b-3b) — but until
 * this class exists the result only ever arrives if somebody calls {@code consume} by hand. In a real
 * deployment the case would therefore sit in {@code EXECUTING} forever while Commerce had already paid: the one
 * gap the ledger named for C05.2c.
 *
 * <p>It is wired by configuration rather than by an annotation processor, and it does one thing: hand the raw
 * bytes to the consumer. Whether a result is acceptable, whether it was seen before, what applying it means to
 * the case and in which order — all of that lives in {@link CaseResultConsumer}, where it is tested against a
 * real database without a broker being involved. The mirror on the other side of this topic is Commerce's
 * {@code RefundCommandListener}, and the two are deliberately the same shape: the acknowledgement decisions
 * below are the ones C05.1b made, read in the other direction.
 *
 * <p><b>Acknowledgement is the interesting decision.</b> The transport is told "consumed" only when the
 * consumer either applied the result or recognised it as a duplicate:
 *
 * <ul>
 *   <li>a redelivery is acknowledged, because the first delivery's fact stands and asking for it forever would
 *       block every result behind it;
 *   <li>a <em>refusal</em> is acknowledged too, deliberately: {@code RefusedEventException} covers everything
 *       that will never become valid — a broken signature, an unknown signing key, a result for an operation
 *       this service never issued, another merchant's case — and none of those answers change by asking again.
 *       The refusal is already recorded in {@code case_result_rejection} (in its own transaction, so the
 *       consumer's rollback cannot erase it), which is where an operator looks; retrying instead would produce
 *       an endless loop whose only trace is a log line, and would hold up the results that are still valid;
 *   <li>anything else — a database that is down, a lock timeout — is <em>not</em> acknowledged, so the broker
 *       redelivers. That is the at-least-once half of the contract, and the inbox is what makes it safe.
 * </ul>
 *
 * <p>It is off unless asked for ({@code resolveflow.events.consumer.enabled}), like every other transport switch
 * in this project: a case-service started without it still creates cases, still dispatches approved
 * authorisations and still records the results it owes, and simply has not been told where to listen. A
 * deployment that enables it and has no broker gets a loud failure at startup rather than a service that looks
 * healthy while no result can reach it.
 */
@Component
@ConditionalOnProperty(name = "resolveflow.events.consumer.enabled", havingValue = "true")
public class RocketMqResultListener implements SmartLifecycle {

    private static final Logger LOG = LoggerFactory.getLogger(RocketMqResultListener.class);

    private final CaseResultConsumer consumer;
    private final String namesrv;
    private final String topic;
    private final String group;
    private DefaultMQPushConsumer pushConsumer;

    public RocketMqResultListener(
            CaseResultConsumer consumer,
            @Value("${resolveflow.events.namesrv:127.0.0.1:9876}") String namesrv,
            // The commerce topic, not this service's own: results are addressed by the producer that owes them
            // (CoreEnvelope.COMMERCE_TOPIC). Subscribing to rf.case.core.v2 — this service's *command* topic —
            // would look entirely healthy and receive nothing, because the two topics are genuinely different
            // queues and only one of them carries results.
            @Value("${resolveflow.events.topics.commerce:" + CoreEnvelope.COMMERCE_TOPIC + "}") String topic,
            // A different group from Commerce's command consumer, and the same name as this service's inbox
            // consumer key: the broker's "who has already seen this" and the inbox's are the same question, so
            // an operator reading either one is reading the same name.
            @Value("${resolveflow.events.consumer.group:" + CaseResultTrustConfiguration.RESULT_CONSUMER + "}")
                    String group) {
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
        // re-apply old results through the inbox (harmless, but pointless work). LAST_OFFSET means the broker's
        // own progress decides, and the inbox covers whatever it redelivers.
        candidate.setConsumeFromWhere(ConsumeFromWhere.CONSUME_FROM_LAST_OFFSET);
        try {
            // Subscribed under the broker's name for this core topic, not the protocol's: RocketMQ refuses the
            // dots in rf.commerce.core.v2, and a consumer that subscribed to the refused name would look healthy
            // while receiving nothing (C05.1c, docs/compatibility-report.md 5.12).
            candidate.subscribe(CoreTopicNames.brokerName(topic), "*");
            candidate.registerMessageListener((MessageListenerConcurrently) (messages, context) -> handle(messages));
            candidate.start();
        } catch (MQClientException cannotStart) {
            // Starting is failed loudly rather than swallowed: a consumer that is not listening would leave
            // cases stuck in EXECUTING while the service looked healthy.
            LOG.error("the refund result listener could not start against {}", namesrv, cannotStart);
            throw new IllegalStateException("refund result listener did not start", cannotStart);
        }
        this.pushConsumer = candidate;
        LOG.info(
                "listening on {} (broker topic {}) for core results (group {})",
                topic,
                CoreTopicNames.brokerName(topic),
                group);
    }

    private ConsumeConcurrentlyStatus handle(java.util.List<MessageExt> messages) {
        for (MessageExt message : messages) {
            String body = new String(message.getBody(), StandardCharsets.UTF_8);
            try {
                CaseResultConsumer.Disposition disposition = consumer.consume(body);
                LOG.debug("core result {} -> {}", message.getMsgId(), disposition);
            } catch (CaseResultVerifier.RefusedEventException refused) {
                // Terminal, and already recorded in case_result_rejection. Acknowledging stops a message that
                // can never become valid from blocking the results queued behind it; the rejection row is what
                // keeps it visible to an operator.
                LOG.warn("core result {} refused: {}", message.getMsgId(), refused.refusal());
            } catch (RuntimeException transientFailure) {
                // Not acknowledged: the broker redelivers, and the inbox makes the second attempt safe.
                LOG.warn(
                        "core result {} could not be applied yet; asking for redelivery",
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
