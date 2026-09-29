package com.resolveflow.caseservice.casefile;

import java.time.Instant;
import org.springframework.stereotype.Component;

/**
 * Retiring the authorisation a case still has alive, because its input moved (C03.3c,
 * docs/domain-model.md:36).
 *
 * <p>An authorisation is created against one input revision and its payload is hashed from that revision's
 * citations (docs/core-contracts.md:68). So the moment the revision moves, the authorisation describes input
 * the case no longer has: whoever approves it afterwards would be approving a payment for material that
 * changed. Leaving it alive and letting the approval path's re-check catch it is not the same guarantee —
 * the window between the two is exactly the window in which the case view says "approved" about the wrong
 * revision.
 *
 * <p>Three routes write new input (material, a verification, a manual proposal), and all three owe that
 * retirement. It lives here once because the alternative is three copies of the same rule, and the copies
 * would drift: the one that forgot would be the one that left a live approval behind, and nothing in the
 * database would complain — the unique key only forbids <em>two</em> live rows.
 *
 * <p>Status is {@code REVOKED} rather than {@code EXPIRED}: somebody's act retired it. The reason is supplied
 * by the caller so the sentence names the act (a proposal, new material) instead of a generic one that a
 * reader cannot act on.
 */
@Component
public class LiveAuthorization {

    private final AuthorizationRepository authorisations;

    public LiveAuthorization(AuthorizationRepository authorisations) {
        this.authorisations = authorisations;
    }

    /** Call while holding the case row lock, including after a failed refund returns it to review. */
    public void requireUnconsumed(String caseId) {
        if (authorisations.hasConsumed(caseId)) {
            throw new CaseStateConflictException("this case has consumed its authorization; its input remains frozen");
        }
    }

    /**
     * Withdraw the case's live authorisation, if it has one, and name it.
     *
     * <p>Missing and racing are different: no live authorisation is the ordinary case (most submissions
     * happen before any run proposed anything), while a row that moved between the read and the write means
     * somebody decided it while the new input was being prepared — that is a conflict, and the caller must
     * not report the input as recorded while the approval it meant to retire is still live.
     *
     * @return the retired authorisation's id, or {@code null} when the case had none alive
     */
    public String revoke(String caseId, String reason, Instant now) {
        AuthorizationRepository.StoredAuthorization live = authorisations.findLatest(caseId);
        if (live == null
                || (live.authorizationStatus() != AuthorizationStatus.PENDING_REVIEW
                        && live.authorizationStatus() != AuthorizationStatus.APPROVED)) {
            return null;
        }
        if (authorisations.revoke(live.authorizationId(), live.authorizationVersion(), reason, now) != 1) {
            throw new CaseStateConflictException("authorisation " + live.authorizationId()
                    + " was decided while the new input was being recorded; nothing was recorded");
        }
        return live.authorizationId();
    }
}
