package com.resolveflow.caseservice.outbox;

/**
 * The transport, as far as the outbox is concerned.
 *
 * <p>One method, because the outbox's responsibility ends at "this envelope was accepted for delivery". Which
 * broker carries it, how many brokers there are and whether it acknowledges with a receipt are not questions
 * the money path should hold an opinion about — and keeping the interface this small is also what lets the
 * retry behaviour be tested without a broker.
 */
public interface EventPublisher {

    /** Raised when the transport refused the envelope; the message is recorded and retried. */
    class PublishException extends RuntimeException {

        private static final long serialVersionUID = 1L;

        public PublishException(String message, Throwable cause) {
            super(message, cause);
        }

        public PublishException(String message) {
            super(message);
        }
    }

    /**
     * Hand one signed envelope to the transport.
     *
     * @param topic the core topic the envelope declares
     * @param envelope the exact text that was signed
     * @param eventId the event's identity, for the transport's own logging
     * @throws PublishException when the transport did not accept it
     */
    void publish(String topic, String envelope, String eventId);
}
