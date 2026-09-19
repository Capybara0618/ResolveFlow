package com.resolveflow.caseservice.casefile;

import com.resolveflow.caseservice.internal.AgentCallbackRequest;
import java.time.Instant;
import java.time.format.DateTimeParseException;
import java.util.List;
import java.util.UUID;
import java.util.regex.Pattern;

/**
 * The member checks the contract asks for, in one place, before anything is applied.
 *
 * <p>Every limit here is copied from {@code AgentCallbackRequest} and its payloads rather than invented: a
 * service that accepted more than the contract declares would be storing deliveries no client can interpret,
 * and a service that accepted less would refuse deliveries the protocol allows.
 *
 * <p>Errors are {@link CaseService.SemanticInvalidException} (422): a delivery that disagrees with the schema,
 * the case binding or the run binding is not a conflict and not a permission problem — it is a body that means
 * nothing, and the contract has exactly one code for that.
 */
final class AgentCallbackValidation {

    /** {@code ReasonCode}: {@code ^[A-Z][A-Z0-9_]{1,63}$}. */
    private static final Pattern REASON_CODE = Pattern.compile("^[A-Z][A-Z0-9_]{1,63}$");

    /** {@code Traceparent}: {@code ^00-[0-9a-f]{32}-[0-9a-f]{16}-[0-9a-f]{2}$}. */
    private static final Pattern TRACEPARENT = Pattern.compile("^00-[0-9a-f]{32}-[0-9a-f]{16}-[0-9a-f]{2}$");

    private static final Pattern UUID_V4_SHAPE =
            Pattern.compile("^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$");

    private static final int MAX_FIELD = 64;

    private static final int MAX_PROMPT = 500;

    private static final int MAX_REASON_CODES = 16;

    private static final int MAX_OBSERVATION_REFS = 32;

    private AgentCallbackValidation() {}

    /** The envelope, read into the shape the writer works with. */
    static AgentCallback envelope(AgentCallbackRequest request) {
        if (request == null) {
            throw new CaseService.SemanticInvalidException("a callback body is required");
        }
        return new AgentCallback(
                requireCallbackId(request.callbackId()),
                requireUuid("run_id", request.runId()),
                requireRevision(request.inputRevision()),
                AgentCallback.Kind.of(request.kind()),
                requirePayload(request.payload()),
                requireTraceparent(request.traceparent()));
    }

    private static String requireCallbackId(String callbackId) {
        if (callbackId == null || callbackId.isBlank()) {
            throw new CaseService.SemanticInvalidException("callback_id is required");
        }
        if (callbackId.length() > AgentCallback.MAX_CALLBACK_ID) {
            throw new CaseService.SemanticInvalidException(
                    "callback_id must be at most " + AgentCallback.MAX_CALLBACK_ID + " characters");
        }
        return callbackId;
    }

    private static String requireUuid(String member, String value) {
        if (value == null || !UUID_V4_SHAPE.matcher(value).matches()) {
            throw new CaseService.SemanticInvalidException(member + " must be a uuid");
        }
        // Parsed as well as matched: the pattern accepts any hex grouping, and a value that is shaped like a
        // uuid but is not one would be stored as an identifier nobody can compare.
        try {
            UUID.fromString(value);
        } catch (IllegalArgumentException error) {
            throw new CaseService.SemanticInvalidException(member + " must be a uuid");
        }
        return value;
    }

    private static int requireRevision(Integer inputRevision) {
        if (inputRevision == null) {
            throw new CaseService.SemanticInvalidException("input_revision is required");
        }
        if (inputRevision < 1) {
            throw new CaseService.SemanticInvalidException("input_revision must be at least 1");
        }
        return inputRevision;
    }

    private static tools.jackson.databind.JsonNode requirePayload(tools.jackson.databind.JsonNode payload) {
        if (payload == null || payload.isNull()) {
            throw new CaseService.SemanticInvalidException("payload is required");
        }
        if (!payload.isObject()) {
            throw new CaseService.SemanticInvalidException("payload must be an object");
        }
        return payload;
    }

    private static String requireTraceparent(String traceparent) {
        if (traceparent == null || traceparent.isBlank()) {
            return null;
        }
        if (!TRACEPARENT.matcher(traceparent).matches()) {
            throw new CaseService.SemanticInvalidException("traceparent must be a W3C trace context header");
        }
        return traceparent;
    }

    static AgentCallback.Started started(AgentCallback.Started started) {
        if (started.startedAt() == null) {
            throw new CaseService.SemanticInvalidException("started_at is required");
        }
        // Read as an instant, not kept as a string: the type is what makes a malformed time fail here rather
        // than when a reader compares it with something.
        try {
            Instant.parse(started.startedAt().toString());
        } catch (DateTimeParseException error) {
            throw new CaseService.SemanticInvalidException("started_at must be a UTC instant");
        }
        return started;
    }

    static AgentCallback.Questions questions(AgentCallback.Questions questions) {
        if (questions.questionId() == null || questions.questionId().isBlank()) {
            throw new CaseService.SemanticInvalidException("question_id is required");
        }
        if (questions.questionId().length() > MAX_FIELD) {
            throw new CaseService.SemanticInvalidException("question_id must be at most " + MAX_FIELD + " characters");
        }
        if (questions.questions() == null || questions.questions().isEmpty()) {
            throw new CaseService.SemanticInvalidException("at least one question is required");
        }
        if (questions.questions().size() > AgentCallback.MAX_QUESTIONS) {
            throw new CaseService.SemanticInvalidException(
                    "at most " + AgentCallback.MAX_QUESTIONS + " questions may be asked at once");
        }
        for (AgentCallback.QuestionItem question : questions.questions()) {
            if (question.field() == null
                    || question.field().isBlank()
                    || question.field().length() > MAX_FIELD) {
                throw new CaseService.SemanticInvalidException(
                        "each question needs a field of at most " + MAX_FIELD + " characters");
            }
            if (question.prompt() == null
                    || question.prompt().isBlank()
                    || question.prompt().length() > MAX_PROMPT) {
                throw new CaseService.SemanticInvalidException(
                        "each question needs a prompt of at most " + MAX_PROMPT + " characters");
            }
        }
        return new AgentCallback.Questions(
                questions.questionId(),
                List.copyOf(questions.questions()),
                reasonCodes(questions.reasonCodes(), false));
    }

    /**
     * A proposal payload is not checked here, and that is deliberate.
     *
     * <p>Its limits belong to the proposal schema, and its members have to agree with the case the delivery
     * was made for — the current revision, the case id, the pinned policy version, the line's own amounts.
     * Those checks need the case row, so they live in {@link ProposalReCheck}, which is also where a refusal
     * becomes a stored REJECTED instead of an error answer. Duplicating half of them here would give a
     * producer two different answers to the same mistake.
     */
    static ProposalSubmission proposal(ProposalSubmission proposal) {
        if (proposal == null) {
            throw new CaseService.SemanticInvalidException("a PROPOSAL callback needs a proposal payload");
        }
        return proposal;
    }

    static AgentCallback.Failure failure(AgentCallback.Failure failure) {
        if (failure.reasonCodes() == null) {
            throw new CaseService.SemanticInvalidException("reason_codes is required");
        }
        List<String> observations = failure.lastObservationRefs();
        if (observations != null && observations.size() > MAX_OBSERVATION_REFS) {
            throw new CaseService.SemanticInvalidException(
                    "at most " + MAX_OBSERVATION_REFS + " last_observation_refs may be reported");
        }
        return new AgentCallback.Failure(reasonCodes(failure.reasonCodes(), true), failure.retryable(), observations);
    }

    private static List<String> reasonCodes(List<String> codes, boolean required) {
        if (codes == null || codes.isEmpty()) {
            if (required) {
                throw new CaseService.SemanticInvalidException("reason_codes must contain at least one code");
            }
            return null;
        }
        if (codes.size() > MAX_REASON_CODES) {
            throw new CaseService.SemanticInvalidException("at most " + MAX_REASON_CODES + " reason codes are allowed");
        }
        for (String code : codes) {
            if (code == null || !REASON_CODE.matcher(code).matches()) {
                throw new CaseService.SemanticInvalidException(
                        "reason codes are upper-case words: " + code + " is not one");
            }
        }
        return List.copyOf(codes);
    }
}
