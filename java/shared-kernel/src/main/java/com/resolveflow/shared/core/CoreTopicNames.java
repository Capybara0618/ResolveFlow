package com.resolveflow.shared.core;

/**
 * The name a core topic is known by on the broker (C05.1c).
 *
 * <p><b>Why this exists at all.</b> The core topic is a member of the signed envelope
 * ({@code topic: rf.case.core.v2}) and the signature deliberately covers it, so that re-addressing a message
 * to another topic invalidates it (C05.1a asserts exactly that). The name is therefore part of the protocol
 * and cannot be re-spelled to suit infrastructure.
 *
 * <p>RocketMQ's classic client, however, accepts only {@code ^[%|a-zA-Z0-9_-]+$} and refuses dots outright:
 *
 * <pre>
 * The specified topic[rf.case.core.v2] contains illegal characters, allowing only ^[%|a-zA-Z0-9_-]+$
 * </pre>
 *
 * <p>Found by running the real broker (C05.1c, docs/compatibility-report.md 5.12) — nothing in a mocked or
 * recording publisher can surface it. The resolution is to keep the protocol's topic in the document and give
 * the transport a name derived from it, at one place both services call, so the producer and the consumer
 * cannot end up addressing different topics while each believes it is using "the" core topic.
 *
 * <p>The mapping is deliberately total over the two core topics and nothing else: a typo must fail here rather
 * than quietly create a second broker topic that no consumer is subscribed to.
 */
public final class CoreTopicNames {

    private CoreTopicNames() {}

    /**
     * The name RocketMQ knows {@code coreTopic} by.
     *
     * @throws IllegalArgumentException if this is not one of the two core topics
     */
    public static String brokerName(String coreTopic) {
        if (coreTopic == null
                || (!CoreEnvelope.CASE_TOPIC.equals(coreTopic) && !CoreEnvelope.COMMERCE_TOPIC.equals(coreTopic))) {
            throw new IllegalArgumentException("not a core topic: " + coreTopic);
        }
        return coreTopic.replace('.', '-');
    }
}
