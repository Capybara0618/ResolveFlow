package com.resolveflow.caseservice.casefile;

import com.resolveflow.caseservice.internal.AgentCallbackRequest;
import org.springframework.dao.DataIntegrityViolationException;
import org.springframework.stereotype.Service;
import tools.jackson.databind.ObjectMapper;

/**
 * Receiving a run's callback (docs/core-contracts.md:59).
 *
 * <p>The route is not idempotent by key and replay: it is idempotent by <b>callback id</b>, which is the
 * delivery's own identity. That difference matters, because a run redelivers on purpose (at-least-once) and
 * the answer has to tell it what happened: ACCEPTED means this delivery applied, DUPLICATE means an identical
 * one already did, STALE means the case has moved on and the run should stop. None of the three is an error,
 * and the two that applied nothing return no version, because no version came from them.
 *
 * <p>The one case that is an error is the same callback id carrying different content: that is not a
 * redelivery, it is a producer that reused an identity, and accepting it would make "which delivery did this?"
 * unanswerable. It is the contract's 409.
 */
@Service
public class AgentCallbackService {

    /** What a delivery did, and at which version of the case. */
    public record Receipt(AgentCallback.Disposition disposition, Long caseVersion, String staleReason) {}

    private final AgentCallbackRepository inbox;
    private final AgentCallbackWriter writer;
    private final ObjectMapper mapper;

    public AgentCallbackService(AgentCallbackRepository inbox, AgentCallbackWriter writer, ObjectMapper mapper) {
        this.inbox = inbox;
        this.writer = writer;
        this.mapper = mapper;
    }

    public Receipt receive(String caseId, AgentCallbackRequest request) {
        AgentCallback callback = AgentCallbackValidation.envelope(request);
        String payloadHash = callback.payloadHash(mapper);
        try {
            return writer.apply(caseId, callback, payloadHash);
        } catch (DataIntegrityViolationException alreadyApplied) {
            return duplicateOrConflict(callback, payloadHash, alreadyApplied);
        }
    }

    /**
     * The delivery lost the race for its own id: either it is the same delivery, or it is not.
     *
     * <p>Read outside the failed transaction on purpose — the insert that lost was rolled back, so the row to
     * compare against is the one the winner wrote. If no row is there, the id is not what collided and the
     * original failure is the truth.
     */
    private Receipt duplicateOrConflict(
            AgentCallback callback, String payloadHash, DataIntegrityViolationException cause) {
        AgentCallbackRepository.StoredDelivery stored = inbox.findByCallbackId(callback.callbackId());
        if (stored == null) {
            throw cause;
        }
        if (!stored.payloadHash().equals(payloadHash)) {
            throw new CaseService.IdempotencyConflictException("callback_id " + callback.callbackId()
                    + " was already delivered with different content; a redelivery repeats the content, it does"
                    + " not change it");
        }
        return new Receipt(AgentCallback.Disposition.DUPLICATE, null, null);
    }
}
