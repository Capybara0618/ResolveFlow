package com.resolveflow.commerce.messaging;

import com.resolveflow.commerce.refund.RefundCommand;
import com.resolveflow.commerce.refund.RefundError;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Propagation;
import org.springframework.transaction.annotation.Transactional;

/**
 * Writing the answer to a refused command, in a transaction of its own (C05.3b).
 *
 * <p>A separate bean rather than a call from {@link RefundCommandConsumer} for one reason, and it is the same
 * reason Commerce's {@code EventRejectionLog} and Case's {@code CaseResultRejectionLog} are separate beans: the
 * consumer's transaction is about to roll back with the refusal, and a row written inside it would roll back
 * too. The row the case needs would be exactly the row that disappeared. {@code REQUIRES_NEW} only works when
 * the call goes through a proxy, so a self-invoked method here would silently join the doomed transaction and
 * the answer would vanish while the code looked right.
 *
 * <p><b>Why the refusal is not simply made non-rolling-back instead.</b> {@code noRollbackFor} on the
 * acceptance path would keep the outer transaction alive, and the consumer could then commit the claim and the
 * answer together — tempting, because it would make a lost acknowledgement harmless (the claim would turn the
 * redelivery into a {@code DUPLICATE}). It is also wrong: a refusal raised <em>after</em> the operation row is
 * inserted (the ledger refusing the reservation, the slot holding it for someone else) would commit the part
 * that ran, leaving an operation with no reservation behind — the half-state the domain forbids
 * (docs/domain-model.md:41). Rollback stays; the answer is what is allowed to outlive it.
 */
@Service
public class RefusedCommandAnswer {

    private final ResultEventOutbox outbox;

    public RefusedCommandAnswer(ResultEventOutbox outbox) {
        this.outbox = outbox;
    }

    /**
     * Record the {@code RefundFailed} a refused command is owed, and return its event id.
     *
     * @param command the command the refusal was about — never null; a message that never parsed into one has
     *     no operation to answer about and is filed as a protocol rejection instead
     */
    @Transactional(propagation = Propagation.REQUIRES_NEW)
    public String record(RefundCommand command, RefundError error) {
        return outbox.writeRefusedCommand(command, error);
    }
}
