package com.resolveflow.commerce.refund;

import java.time.Clock;
import java.time.Instant;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import tools.jackson.databind.JsonNode;
import tools.jackson.databind.ObjectMapper;

/**
 * Accepting a refund command, and reserving the money for it
 * (docs/domain-model.md:47, the "处理命令" line).
 *
 * <p>The order inside the transaction is the design, and each step exists because of what it prevents:
 *
 * <ol>
 *   <li><b>Parse and re-derive the hash first.</b> A command whose {@code payload_hash} does not cover its
 *       own members is refused before anything is written, because it is a command about a different payment
 *       than the one that was approved (docs/core-contracts.md:19).
 *   <li><b>Then the operation id.</b> A known id is answered from the record — the same payload returns that
 *       record (idempotency), a different payload is refused (docs/domain-model.md:11). A redelivery
 *       therefore cannot become a second reservation, and a changed payload cannot become a second payment
 *       under an approved hash.
 *   <li><b>Then the delivery id.</b> One request id re-sent with different money is a client bug, not a
 *       duplicate, and is refused rather than answered.
 *   <li><b>Then lock the ledger, then the line slot.</b> That order is fixed here and in
 *       {@link RefundMoneyRepository} so two refunds for two lines of one order cannot deadlock.
 *   <li><b>Then check the world.</b> The line must exist, belong to the command's merchant, and its amount,
 *       quantity and currency must be the command's — a core refund is the whole line at its own paid price
 *       (docs/product-spec.md:13), so a different amount is not a smaller refund, it is the wrong command.
 *   <li><b>Then reserve, and only then claim the line.</b> Both writes are conditional statements, so a
 *       concurrent operation for the same line loses in the database rather than in a check that could race.
 * </ol>
 *
 * <p>The provider is not called here. Reserving money locally and telling the outside world are separate
 * facts, and a transaction that held a database lock across a network call would be both slow and wrong
 * (docs/engineering.md:23).
 */
@Service
public class RefundAcceptanceService {

    private final RefundOperationRepository operations;
    private final RefundMoneyRepository money;
    private final RefundRequestInboxRepository inbox;
    private final Clock clock;
    private final ObjectMapper mapper;

    public RefundAcceptanceService(
            RefundOperationRepository operations,
            RefundMoneyRepository money,
            RefundRequestInboxRepository inbox,
            Clock clock,
            ObjectMapper mapper) {
        this.operations = operations;
        this.money = money;
        this.inbox = inbox;
        this.clock = clock;
        this.mapper = mapper;
    }

    /**
     * What this service did with one delivery.
     *
     * <p>{@code replayed} is not a detail: it is the difference between "this command reserved money now" and
     * "this command had already reserved it", which is what makes a retry safe to send.
     */
    public record Receipt(RefundOperationRepository.StoredOperation operation, boolean replayed) {}

    @Transactional
    public Receipt accept(String requestId, JsonNode document) {
        if (requestId == null || requestId.isBlank()) {
            throw new RefundRejectedException(
                    RefundError.MALFORMED_COMMAND, "a command arrives with the delivery id that identifies it");
        }
        RefundCommand command = RefundCommand.parse(mapper, document);
        // Every refusal from here on is about a command this service understood, so every one of them carries
        // it (C05.3b): the consumer answers the case with a RefundFailed naming the operation id, and a throw
        // site added later cannot forget to attach it because the attaching happens once, here.
        try {
            return acceptParsed(requestId, command);
        } catch (RefundRejectedException refused) {
            throw refused.withCommand(command);
        }
    }

    private Receipt acceptParsed(String requestId, RefundCommand command) {
        Instant now = Instant.now(clock);

        RefundOperationRepository.StoredOperation existing = operations.find(command.operationId());
        if (existing != null) {
            return new Receipt(requireSamePayment(existing, command), true);
        }

        // Read-only check here, the row itself after the operation exists: the inbox has a foreign key to the
        // operation, and claiming a delivery for an operation that is not written yet would be a claim on
        // nothing. What matters is that a reuse of the delivery id is caught inside this transaction, and the
        // insert that follows is part of it.
        requireUnusedDeliveryId(requestId, command);

        String orderId = money.findLineOrderId(command.lineId());
        if (orderId == null) {
            throw new RefundRejectedException(RefundError.LINE_NOT_FOUND, "no order line " + command.lineId());
        }
        RefundMoneyRepository.LedgerRow ledger = money.lockLedger(orderId);
        if (ledger == null) {
            throw new RefundRejectedException(RefundError.AMOUNT_MISMATCH, "the order has no payment ledger");
        }
        // The first lookup can precede a concurrent delivery's commit. Read the current row under
        // the ledger lock: a REPEATABLE READ snapshot would still miss it and falsely emit failure
        // for an operation that has already reserved this very line.
        existing = operations.findForUpdate(command.operationId());
        if (existing != null) {
            return new Receipt(requireSamePayment(existing, command), true);
        }
        RefundMoneyRepository.RefundSlot slot = money.slotForUpdate(command.lineId());
        if (slot == null) {
            throw new RefundRejectedException(
                    RefundError.LINE_NOT_FOUND, "no order line " + command.lineId() + " in this service");
        }
        requireRefundable(slot, command);

        operations.insert(
                command.operationId(),
                command.authorizationId(),
                command.caseId(),
                command.inputRevision(),
                command.merchantId(),
                command.lineId(),
                command.action(),
                command.quantity(),
                command.currency(),
                command.amountMinor(),
                command.payloadHash(),
                command.policyVersion(),
                "RECEIVED",
                // The provider's key is the operation id, decided here so it is fixed before the provider is
                // ever called (docs/domain-model.md:51).
                command.operationId(),
                now);

        // The delivery is claimed only once the operation it names exists. A redelivery of *this* command
        // never reaches here (the operation lookup answers it above), so a row here means a first delivery.
        inbox.insert(requestId, command.operationId(), command.payloadHash(), now);

        if (money.reserveInLedger(ledger.orderId(), command.amountMinor()) != 1) {
            // The ledger refused: the order's paid amount is already accounted for by another line's refund
            // (or by a reservation this transaction did not make). That is a state of the world, not a fault
            // in the message.
            throw new RefundRejectedException(
                    RefundError.AMOUNT_MISMATCH,
                    "order " + ledger.orderId() + " cannot reserve " + command.amountMinor()
                            + " more: paid " + ledger.paidAmount() + ", refunded " + ledger.refundedAmount()
                            + ", reserved " + ledger.reservedRefundAmount());
        }
        if (money.holdForRefund(command.lineId(), command.operationId(), now) != 1) {
            // Between reading the slot and holding it, another operation took the line. Rolling back is the
            // honest answer: this command reserved nothing.
            throw new RefundRejectedException(
                    RefundError.ANOTHER_OPERATION_LIVE, "another operation took line " + command.lineId());
        }

        RefundOperationRepository.StoredOperation stored = operations.find(command.operationId());
        assert stored != null : "the operation row was just written";
        return new Receipt(stored, false);
    }

    /**
     * A known operation id is only the same payment if it carries the same payload.
     *
     * <p>The comparison is on the hash rather than on the members: the hash is what the authorisation fixed,
     * so two commands with equal hashes are the same command by construction, and a different hash under one
     * operation id is exactly the "same id, different payload" case the domain refuses
     * (docs/domain-model.md:11).
     */
    private RefundOperationRepository.StoredOperation requireSamePayment(
            RefundOperationRepository.StoredOperation stored, RefundCommand command) {
        if (!stored.payloadHash().equals(command.payloadHash())) {
            throw new RefundRejectedException(
                    RefundError.PAYLOAD_HASH_MISMATCH,
                    "operation " + command.operationId() + " already exists for a different payload");
        }
        return stored;
    }

    /**
     * Refuse a delivery id this service has already used for different money.
     *
     * <p>A repeat of the same delivery id carrying the same command is answered by the operation lookup above
     * and never reaches this method. What reaches here is a client reusing one identifier for two commands,
     * which is a bug in the producer rather than a duplicate, and answering it with somebody else's refund
     * would hide the bug behind a wrong success.
     */
    private void requireUnusedDeliveryId(String requestId, RefundCommand command) {
        RefundRequestInboxRepository.StoredRequest seen = inbox.find(requestId);
        if (seen == null) {
            return;
        }
        if (seen.operationId().equals(command.operationId())
                && seen.payloadHash().equals(command.payloadHash())) {
            return;
        }
        throw new RefundRejectedException(
                RefundError.MALFORMED_COMMAND, "delivery id " + requestId + " was already used for another command");
    }

    /** The world checks, in the order a reader would ask them. */
    private void requireRefundable(RefundMoneyRepository.RefundSlot slot, RefundCommand command) {
        if (!slot.merchantId().equals(command.merchantId())) {
            throw new RefundRejectedException(
                    RefundError.LINE_OWNER_MISMATCH, "line " + command.lineId() + " belongs to " + slot.merchantId());
        }
        if ("CONSUMED".equals(slot.state())) {
            throw new RefundRejectedException(
                    RefundError.ALREADY_REFUNDED,
                    "line " + command.lineId() + " was already refunded by operation " + slot.holdingOperationId());
        }
        if ("RESERVED".equals(slot.state())) {
            throw new RefundRejectedException(
                    RefundError.ANOTHER_OPERATION_LIVE,
                    "line " + command.lineId() + " is held by operation " + slot.holdingOperationId());
        }
        if (slot.linePaidAmount() != command.amountMinor()) {
            throw new RefundRejectedException(
                    RefundError.AMOUNT_MISMATCH,
                    "line " + command.lineId() + " was paid " + slot.linePaidAmount() + ", not "
                            + command.amountMinor());
        }
        if (slot.quantity() != command.quantity()) {
            throw new RefundRejectedException(
                    RefundError.QUANTITY_MISMATCH,
                    "a core refund is the line's whole quantity " + slot.quantity() + ", not " + command.quantity());
        }
        if (!slot.currency().equals(command.currency())) {
            throw new RefundRejectedException(
                    RefundError.CURRENCY_MISMATCH, "line " + command.lineId() + " is priced in " + slot.currency());
        }
    }
}
