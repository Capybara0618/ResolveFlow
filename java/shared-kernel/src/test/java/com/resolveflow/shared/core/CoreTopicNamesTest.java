package com.resolveflow.shared.core;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

/**
 * The broker's view of a core topic (C05.1c).
 *
 * <p>This class exists because the broker refuses the protocol's own topic name, so the point of these tests is
 * narrow and load-bearing: the derived name must be one RocketMQ accepts, the two core topics must not collide
 * after the mapping, and a name that is not a core topic must fail rather than invent a broker topic.
 */
class CoreTopicNamesTest {

    /** RocketMQ's own rule, copied from the message it answers with. */
    private static final String ROCKETMQ_ALLOWED = "^[%|a-zA-Z0-9_-]+$";

    @Test
    @DisplayName("a core topic becomes a name RocketMQ accepts")
    void coreTopicsBecomeBrokerLegalNames() {
        assertThat(CoreTopicNames.brokerName(CoreEnvelope.CASE_TOPIC))
                .as("the protocol keeps rf.case.core.v2; the broker gets this")
                .isEqualTo("rf-case-core-v2")
                .matches(ROCKETMQ_ALLOWED);
        assertThat(CoreTopicNames.brokerName(CoreEnvelope.COMMERCE_TOPIC))
                .isEqualTo("rf-commerce-core-v2")
                .matches(ROCKETMQ_ALLOWED);
        assertThat(CoreTopicNames.brokerName(CoreEnvelope.CASE_TOPIC))
                .as("the two directions must not land on one topic")
                .isNotEqualTo(CoreTopicNames.brokerName(CoreEnvelope.COMMERCE_TOPIC));
        assertThat(CoreEnvelope.CASE_TOPIC)
                .as("and the protocol's name is indeed the one the broker would refuse")
                .doesNotMatch(ROCKETMQ_ALLOWED);
    }

    @Test
    @DisplayName("anything that is not a core topic is refused instead of being mapped to somebody's topic")
    void onlyCoreTopicsAreMapped() {
        assertThatThrownBy(() -> CoreTopicNames.brokerName("rf.case.core.v3"))
                .isInstanceOf(IllegalArgumentException.class)
                .hasMessageContaining("not a core topic");
        assertThatThrownBy(() -> CoreTopicNames.brokerName(null)).isInstanceOf(IllegalArgumentException.class);
    }

    @Test
    @DisplayName("the mapping is stable, so producer and consumer derive the same name from the same document")
    void theMappingIsStable() {
        String first = CoreTopicNames.brokerName(CoreEnvelope.CASE_TOPIC);
        String second = CoreTopicNames.brokerName(CoreEnvelope.CASE_TOPIC);
        assertThat(first).isEqualTo(second);
        assertThat(first).doesNotContain(".");
    }
}
