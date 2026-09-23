package com.resolveflow.commerce.messaging;

/**
 * Handing a signed envelope to a transport (C05.2b), the same narrow port the case side uses (C05.1b).
 *
 * <p>A one-method interface on purpose: what the delivery service needs is "put these bytes on this topic, and
 * throw if you did not", and everything else about a broker — connections, retries inside the client, keys,
 * batching — is the implementation's business. It also makes the at-least-once behaviour testable without a
 * broker, which is how the failure and give-up paths are exercised at all.
 */
public interface EventPublisher {

    /**
     * Publish one signed envelope, or throw.
     *
     * @param topic the protocol's topic (for example {@code rf.commerce.core.v2}); the transport derives
     *     whatever name it needs (C05.1c: the broker refuses dots)
     * @param envelope the signed document, exactly as it was stored
     * @param eventId the event's own id, so an operator can find it in the transport's tooling
     */
    void publish(String topic, String envelope, String eventId);
}
