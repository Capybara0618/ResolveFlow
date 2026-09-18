package com.resolveflow.spike;

import org.apache.rocketmq.client.consumer.DefaultMQPushConsumer;
import org.apache.rocketmq.client.consumer.listener.ConsumeConcurrentlyStatus;
import org.apache.rocketmq.client.consumer.listener.MessageListenerConcurrently;
import org.apache.rocketmq.client.producer.DefaultMQProducer;
import org.apache.rocketmq.client.producer.SendResult;
import org.apache.rocketmq.client.producer.SendStatus;
import org.apache.rocketmq.common.consumer.ConsumeFromWhere;
import org.apache.rocketmq.common.message.Message;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import java.nio.charset.StandardCharsets;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicReference;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

/**
 * T00 gate: can the SCA-managed classic RocketMQ client actually talk to a real
 * RocketMQ 5.x NameServer + Broker, in the two-container shape the project assumes?
 *
 * <p>Needs the spike stack up:
 * {@code docker compose -f spikes/compatibility/infra/spike-compose.yaml up -d}
 */
class RocketMqIT {

    static final String NAMESRV = System.getProperty("spike.namesrv", "127.0.0.1:19876");

    @Test
    @DisplayName("A real event round-trips through RocketMQ 5.x with its payload intact")
    void sendAndConsumeRealEvent() throws Exception {
        String topic = "spike-order-events";
        String tag = "OrderPaid";
        // JSON payload with a UTF-8 Chinese field, the way business events will look.
        String payload = "{\"event\":\"OrderPaid\",\"orderId\":9001,\"amountMinor\":20000,\"note\":\"模拟事件\"}";

        DefaultMQProducer producer = new DefaultMQProducer("spike-producer-group");
        producer.setNamesrvAddr(NAMESRV);
        producer.setSendMsgTimeout(5_000);
        producer.start();
        try {
            Message message = new Message(topic, tag, payload.getBytes(StandardCharsets.UTF_8));
            // Key carries the business id, so duplicate delivery can be detected downstream.
            message.setKeys("order-9001");
            SendResult result = producer.send(message);

            assertThat(result.getSendStatus())
                    .as("broker must acknowledge the send")
                    .isEqualTo(SendStatus.SEND_OK);
            assertThat(result.getMsgId()).isNotBlank();
        } finally {
            producer.shutdown();
        }

        CountDownLatch latch = new CountDownLatch(1);
        AtomicReference<String> receivedBody = new AtomicReference<>();
        AtomicReference<String> receivedKeys = new AtomicReference<>();

        DefaultMQPushConsumer consumer = new DefaultMQPushConsumer("spike-consumer-group");
        consumer.setNamesrvAddr(NAMESRV);
        consumer.setConsumeFromWhere(ConsumeFromWhere.CONSUME_FROM_FIRST_OFFSET);
        consumer.subscribe(topic, tag);
        consumer.registerMessageListener((MessageListenerConcurrently) (msgs, context) -> {
            receivedBody.set(new String(msgs.get(0).getBody(), StandardCharsets.UTF_8));
            receivedKeys.set(msgs.get(0).getKeys());
            latch.countDown();
            return ConsumeConcurrentlyStatus.CONSUME_SUCCESS;
        });
        consumer.start();
        try {
            assertThat(latch.await(30, TimeUnit.SECONDS))
                    .as("the consumer must receive the event within 30s")
                    .isTrue();
            assertThat(receivedBody.get()).isEqualTo(payload);
            assertThat(receivedKeys.get()).isEqualTo("order-9001");
        } finally {
            consumer.shutdown();
        }
    }

    @Test
    @DisplayName("An unreachable NameServer fails fast instead of silently succeeding")
    void unreachableNameServerDoesNotSilentlySucceed() {
        DefaultMQProducer producer = new DefaultMQProducer("spike-bad-namesrv-group");
        // Deliberately wrong address: the gate is that this is loud, not that it retries forever.
        producer.setNamesrvAddr("127.0.0.1:1");
        producer.setSendMsgTimeout(2_000);
        producer.setRetryTimesWhenSendFailed(0);

        assertThatThrownBy(() -> {
            producer.start();
            producer.send(new Message("spike-order-events", "nobody-listening".getBytes(StandardCharsets.UTF_8)));
        }).isInstanceOf(Exception.class);
    }
}