package com.resolveflow.commerce.refund;

import java.time.Duration;
import java.time.Instant;
import java.util.List;
import java.util.Objects;
import org.springframework.stereotype.Service;
import org.springframework.transaction.support.TransactionTemplate;

/**
 * Calling the provider, and settling what it answered (C04.3, docs/domain-model.md:49,51).
 *
 * <p>The shape of this class is the whole point: <b>the network call is never inside a transaction</b>
 * (docs/engineering.md:23). Every dispatch and every reconciliation is three moments, and each is its own
 * transaction:
 *
 * <ol>
 *   <li><b>Before the call</b>, the operation moves to {@code IN_PROGRESS} and that commits. The reservation
 *       is already durable, so if this process dies between here and the answer the money stays reserved and
 *       the operation stays findable — which is what makes the retry path possible at all.
 *   <li><b>The call itself</b>, holding no database lock. A provider that takes five seconds must not hold a
 *       line's row for five seconds.
 *   <li><b>After the answer</b>, one transaction applies it: the operation's state, the ledger's amounts and
 *       the line's slot move together (C04.2). Re-entering this is safe by construction — the settlement
 *       statements carry the state they expect.
 * </ol>
 *
 * <p>An answer of {@code UNKNOWN} (or no answer, or a 404) is not a failure and releases nothing: it is
 * recorded as {@code UNKNOWN} with a next-attempt time, and the reservation stays
 * (docs/domain-model.md:15 — UNKNOWN不释放金额).
 */
@Service
public class RefundDispatchService {

    /** How long to wait before asking the provider again about an unresolved operation. */
    private static final Duration RETRY_BACKOFF = Duration.ofSeconds(30);

    private final RefundProviderClient provider;
    private final RefundOperationRepository operations;
    private final RefundSettlementService settlements;
    private final TransactionTemplate transactions;

    public RefundDispatchService(
            RefundProviderClient provider,
            RefundOperationRepository operations,
            RefundSettlementService settlements,
            TransactionTemplate transactions) {
        this.provider = provider;
        this.operations = operations;
        this.settlements = settlements;
        this.transactions = transactions;
    }

    /**
     * Send one already-reserved refund to the provider and settle it.
     *
     * @return the stored operation as it stands after the attempt
     */
    public RefundOperationRepository.StoredOperation dispatch(String operationId) {
        RefundOperationRepository.StoredOperation claimed = transactions.execute(status -> claim(operationId));
        if (claimed == null) {
            // The claim refused: the operation is already terminal, or somebody else is talking to the
            // provider about it right now. Answering with the stored row is the honest response; sending a
            // second request would be a second payment attempt under the same key.
            return require(operationId);
        }

        RefundProviderClient.ProviderAnswer answer = provider.requestRefund(
                claimed.operationId(), claimed.lineId(), claimed.amountMinor(), claimed.currency());

        return transactions.execute(status -> apply(operationId, answer));
    }

    /**
     * Ask the provider what happened to an operation whose outcome is still unknown.
     *
     * <p>This is the reconciliation half, and it is a *read* at the provider rather than a re-request: the
     * operation was already sent, so asking it to pay again would be wrong — asking what happened is the
     * only question left (docs/domain-model.md:49, 所有终局更新检查前置状态/版本).
     */
    public RefundOperationRepository.StoredOperation reconcile(String operationId) {
        require(operationId);
        RefundProviderClient.ProviderAnswer answer = provider.queryRefund(operationId);
        return transactions.execute(status -> apply(operationId, answer));
    }

    /**
     * Resolve every operation that has waited past its retry time.
     *
     * <p>The due list is read in one short transaction and the provider calls happen after it closes: a pass
     * that held a transaction across N network calls would hold locks for as long as the slowest provider
     * answer, which is the thing this class exists to avoid.
     *
     * @param limit how many to attempt in one pass, so a backlog is worked through in bounded steps
     * @return the number of operations this pass looked at
     */
    public int reconcileDue(int limit) {
        List<String> due = Objects.requireNonNull(
                transactions.execute(status -> operations.findDueForReconciliation(Instant.now(), limit)));
        for (String operationId : due) {
            reconcile(operationId);
        }
        return due.size();
    }

    // ------------------------------------------------------------------ transactions

    /** Move an operation to IN_PROGRESS, or refuse because it is finished or already being sent. */
    private RefundOperationRepository.StoredOperation claim(String operationId) {
        RefundOperationRepository.StoredOperation operation = require(operationId);
        if (isTerminal(operation.state())) {
            return null;
        }
        if (operations.markInProgress(operationId) != 1) {
            return null;
        }
        return require(operationId);
    }

    /** Apply one provider answer in its own transaction. */
    private RefundOperationRepository.StoredOperation apply(
            String operationId, RefundProviderClient.ProviderAnswer answer) {
        if (answer.isRefunded()) {
            return settlements.settleSucceeded(operationId, answer.providerRef());
        }
        if (answer.isRefused()) {
            return settlements.settleFailed(
                    operationId, answer.reasonCode() == null ? "DECLINED" : answer.reasonCode());
        }
        // UNKNOWN, NOT_FOUND, or a lost response: nothing has been decided *on this side*, so nothing is
        // released. A lost response is the interesting one — the provider did settle, and only the retry under
        // the same key can recover the outcome; settling it here would make the retry a no-op and leave this
        // service claiming a result it never received (fixtures/provider/README.md §1).
        RefundOperationRepository.StoredOperation operation = require(operationId);
        if (isTerminal(operation.state())) {
            return operation;
        }
        // Through the settlement service rather than the repository directly, so the transition and the result
        // event it owes the case share one transaction (C05.2b): a lost response the case never hears about is
        // a case that keeps waiting for an answer this service already recorded as absent.
        return settlements.settleUnknown(
                operationId,
                answer.reasonCode() == null ? reasonFor(answer) : answer.reasonCode(),
                Instant.now().plus(RETRY_BACKOFF));
    }

    /**
     * Why this attempt did not settle, in a word a later reader can act on.
     *
     * <p>A lost response and a provider that said nothing are different facts: the first needs no change of
     * behaviour, the second may need the provider looked at. Recording both as one code would hide that.
     */
    private static String reasonFor(RefundProviderClient.ProviderAnswer answer) {
        if (!answer.responded() && "SUCCEEDED".equals(answer.state())) {
            return "PROVIDER_RESPONSE_LOST";
        }
        return "PROVIDER_NO_ANSWER";
    }

    private RefundOperationRepository.StoredOperation require(String operationId) {
        RefundOperationRepository.StoredOperation operation = operations.find(operationId);
        if (operation == null) {
            throw new IllegalArgumentException("no refund operation " + operationId);
        }
        return operation;
    }

    private static boolean isTerminal(String state) {
        return "SUCCEEDED".equals(state) || "FAILED".equals(state);
    }

    /** The retry window this service records, exposed so a caller can reason about it without magic numbers. */
    public static Duration retryBackoff() {
        return RETRY_BACKOFF;
    }
}
