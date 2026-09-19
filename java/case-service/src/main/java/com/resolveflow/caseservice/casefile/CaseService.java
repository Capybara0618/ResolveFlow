package com.resolveflow.caseservice.casefile;

import com.resolveflow.shared.contract.CanonicalJson;
import com.resolveflow.shared.security.AuthenticatedPrincipal;
import com.resolveflow.shared.security.Role;
import java.time.Clock;
import java.time.Instant;
import java.util.ArrayList;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Set;
import java.util.UUID;
import org.springframework.dao.DuplicateKeyException;
import org.springframework.stereotype.Service;
import tools.jackson.databind.ObjectMapper;
import tools.jackson.databind.node.ObjectNode;

/**
 * Opening a refund case (docs/core-contracts.md:28).
 *
 * <p>The order of operations is the design:
 *
 * <ol>
 *   <li>The principal must be the customer. A merchant-scoped token has nobody to attribute the case
 *       to, and merchant staff work the review queue instead (docs/core-contracts.md:33), so such a
 *       request is refused rather than attributed to a guessed customer.
 *   <li>The line must be inside the caller's scope, asked of Commerce with the scope derived from the
 *       token. A line that is not theirs is answered 404, like any other invisible resource
 *       (docs/core-contracts.md:27) — the case table then holds the order id Commerce reported, not one
 *       the client sent.
 *   <li>Only then is a transaction opened. The Commerce call is a network call, and a network call
 *       does not belong inside a database transaction (docs/engineering.md:68).
 *   <li>The case, its requested actions, its active slot, its first trajectory entry and the stored
 *       idempotent answer are written in one transaction: an inbox entry or a local event that
 *       disagreed with the business result would be a lie about what happened.
 * </ol>
 *
 * <p>The same key with the same body replays the stored answer verbatim; the same key with a different
 * body is 409. The stored answer is what is replayed rather than the case's current state, because an
 * old key must not start reporting later changes (docs/core-contracts.md:15).
 */
@Service
public class CaseService {

    /** A create request that is well formed but asks for something core cannot honour. */
    public static class SemanticInvalidException extends RuntimeException {

        private static final long serialVersionUID = 1L;

        public SemanticInvalidException(String message) {
            super(message);
        }
    }

    /** The same idempotency key with a different body. */
    public static class IdempotencyConflictException extends RuntimeException {

        private static final long serialVersionUID = 1L;

        public IdempotencyConflictException() {
            super("this idempotency key was already used with a different body");
        }
    }

    /** The line already has an open case. */
    public static class CaseAlreadyOpenException extends RuntimeException {

        private static final long serialVersionUID = 1L;

        public CaseAlreadyOpenException() {
            super("this line already has an open case");
        }
    }

    /** The line is not inside the caller's scope, or does not exist. */
    public static class LineNotVisibleException extends RuntimeException {

        private static final long serialVersionUID = 1L;

        public LineNotVisibleException() {
            super("the line does not exist under this principal");
        }
    }

    /** A merchant-scoped principal cannot open a case: a case belongs to one customer. */
    public static class ForbiddenScopeException extends RuntimeException {

        private static final long serialVersionUID = 1L;

        public ForbiddenScopeException(String message) {
            super(message);
        }
    }

    /** The Idempotency-Key header is required on this route (docs/core-contracts.md:15). */
    public static class MissingIdempotencyKeyException extends RuntimeException {

        private static final long serialVersionUID = 1L;

        public MissingIdempotencyKeyException() {
            super("this route requires an Idempotency-Key header");
        }
    }

    /** What the caller gets back, plus whether it was created now or replayed. */
    public record Created(CaseCreatedResponse body, boolean replayed) {}

    private final CaseRepository cases;
    private final CaseWriter writer;
    private final CommerceLineLookup commerce;
    private final Clock clock;
    private final ObjectMapper mapper = new ObjectMapper();

    public CaseService(CaseRepository cases, CaseWriter writer, CommerceLineLookup commerce, Clock clock) {
        this.cases = cases;
        this.writer = writer;
        this.commerce = commerce;
        this.clock = clock;
    }

    public Created create(AuthenticatedPrincipal principal, String idempotencyKey, CaseCreateRequest request) {
        if (idempotencyKey == null || idempotencyKey.isBlank()) {
            throw new MissingIdempotencyKeyException();
        }
        if (idempotencyKey.length() > 128) {
            throw new SemanticInvalidException("the idempotency key must be at most 128 characters");
        }
        if (principal.role() != Role.CUSTOMER) {
            throw new ForbiddenScopeException(
                    "a case is opened by the customer it belongs to; merchant staff work the review queue");
        }
        List<RequestedAction> actions = parseActions(request);
        String lineId = requireLineId(request);
        String description = requireDescription(request);
        String requestHash = requestHash(lineId, description, actions);

        CaseRepository.StoredResponse stored = cases.findIdempotency(principal.merchantId(), idempotencyKey);
        if (stored != null) {
            return replay(stored, requestHash);
        }

        // The scope is the token's, and Commerce answers with the order the line really belongs to.
        CommerceLineLookup.Line line = commerce.findLine(principal, lineId).orElseThrow(LineNotVisibleException::new);

        Instant now = Instant.now(clock);
        String caseId = UUID.randomUUID().toString();
        try {
            return writer.writeCase(new CaseWriter.CaseWrite(
                    caseId,
                    principal.merchantId(),
                    principal.customerId(),
                    line.orderId(),
                    lineId,
                    actions,
                    description,
                    idempotencyKey,
                    requestHash,
                    now));
        } catch (DuplicateKeyException error) {
            // Two unique keys can collide here, and they mean different things.
            CaseRepository.StoredResponse raced = cases.findIdempotency(principal.merchantId(), idempotencyKey);
            if (raced != null && raced.requestHash().equals(requestHash)) {
                return replay(raced, requestHash);
            }
            if (raced != null) {
                throw new IdempotencyConflictException();
            }
            throw new CaseAlreadyOpenException();
        }
    }

    private Created replay(CaseRepository.StoredResponse stored, String requestHash) {
        if (!stored.requestHash().equals(requestHash)) {
            throw new IdempotencyConflictException();
        }
        return new Created(readBack(stored.responseBody()), true);
    }

    private CaseCreatedResponse readBack(String responseBody) {
        return mapper.readValue(responseBody, CaseCreatedResponse.class);
    }

    private List<RequestedAction> parseActions(CaseCreateRequest request) {
        List<String> requested = request.requestedActions();
        if (requested == null || requested.isEmpty()) {
            throw new SemanticInvalidException("at least one requested action is required");
        }
        if (requested.size() > 3) {
            throw new SemanticInvalidException("at most three requested actions are allowed");
        }
        Set<String> unique = new LinkedHashSet<>(requested);
        if (unique.size() != requested.size()) {
            throw new SemanticInvalidException("the requested actions must be distinct");
        }
        List<RequestedAction> actions = new ArrayList<>(unique.size());
        for (String action : unique) {
            try {
                actions.add(RequestedAction.of(action));
            } catch (IllegalArgumentException error) {
                throw new SemanticInvalidException(error.getMessage());
            }
        }
        return List.copyOf(actions);
    }

    private static String requireLineId(CaseCreateRequest request) {
        if (request.lineId() == null || request.lineId().isBlank()) {
            throw new SemanticInvalidException("line_id is required");
        }
        if (request.lineId().length() > 64) {
            throw new SemanticInvalidException("line_id must be at most 64 characters");
        }
        return request.lineId();
    }

    private static String requireDescription(CaseCreateRequest request) {
        if (request.description() == null || request.description().isBlank()) {
            throw new SemanticInvalidException("a description is required");
        }
        if (request.description().length() > 4000) {
            throw new SemanticInvalidException("the description must be at most 4000 characters");
        }
        return request.description();
    }

    /**
     * The hash that decides "same body": the canonical form of the members that define the request,
     * with the actions sorted, so two spellings of the same request are the same request.
     */
    private String requestHash(String lineId, String description, List<RequestedAction> actions) {
        ObjectNode node = mapper.createObjectNode();
        node.put("line_id", lineId);
        node.put("description", description);
        List<String> names = actions.stream().map(Enum::name).sorted().toList();
        node.putArray("requested_actions")
                .addAll(names.stream()
                        .map(name -> mapper.getNodeFactory().stringNode(name))
                        .toList());
        return CanonicalJson.contentHash(node);
    }
}
