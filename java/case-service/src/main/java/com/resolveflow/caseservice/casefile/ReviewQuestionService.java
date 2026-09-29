package com.resolveflow.caseservice.casefile;

import com.resolveflow.shared.contract.CanonicalJson;
import com.resolveflow.shared.security.AuthenticatedPrincipal;
import java.time.Clock;
import java.time.Instant;
import java.util.UUID;
import org.springframework.stereotype.Service;
import tools.jackson.databind.ObjectMapper;
import tools.jackson.databind.node.ObjectNode;

/** Shared guard and trajectory writer for both reviewer REQUEST_INFO routes. */
@Service
public class ReviewQuestionService {

    private static final int MAX_ROUNDS = 2;

    private final CaseRepository cases;
    private final Clock clock;
    private final ObjectMapper mapper;

    public ReviewQuestionService(CaseRepository cases, Clock clock, ObjectMapper mapper) {
        this.cases = cases;
        this.clock = clock;
        this.mapper = mapper;
    }

    public void requireAllowed(CaseRow row) {
        String refusal = refusal(row);
        if (refusal != null) throw new CaseStateConflictException(refusal);
    }

    public boolean isAllowed(CaseRow row) {
        return refusal(row) == null;
    }

    private String refusal(CaseRow row) {
        if (row.status() == CaseStatus.WAITING_CUSTOMER) {
            return "the case is already waiting for the customer's answer";
        }
        long rounds = cases.findTimeline(row.caseId()).stream()
                .filter(event -> event.kind() == TimelineEventType.QUESTION_REQUIRED)
                .count();
        if (rounds >= MAX_ROUNDS) {
            return "the case has already used its two information-request rounds";
        }
        Instant now = Instant.now(clock);
        if (row.expiresAt() != null && !now.isBefore(row.expiresAt())) {
            return "the case has expired, so no further information can be requested";
        }
        return null;
    }

    public String record(
            CaseRow row, int revision, AuthenticatedPrincipal principal, String reason, String origin, Instant now) {
        String questionId = UUID.randomUUID().toString();
        ObjectNode detail = mapper.createObjectNode();
        detail.put("origin", origin);
        detail.put("decision", "REQUEST_INFO");
        detail.put("reason", reason);
        detail.put("decided_by", principal.subject());
        detail.put("decided_role", principal.role().name());
        detail.put("status", CaseStatus.WAITING_CUSTOMER.name());
        detail.put("question_id", questionId);
        detail.putArray("questions")
                .addObject()
                .put("field", "additional_evidence")
                .put("prompt", reason);
        cases.insertTimeline(
                row.caseId(),
                UUID.randomUUID().toString(),
                cases.nextTimelineSequence(row.caseId()),
                TimelineEventType.QUESTION_REQUIRED.name(),
                CanonicalJson.canonicalize(detail),
                now,
                revision);
        return questionId;
    }
}
