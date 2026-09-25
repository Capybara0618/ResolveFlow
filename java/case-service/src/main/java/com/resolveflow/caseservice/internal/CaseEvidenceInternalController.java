package com.resolveflow.caseservice.internal;

import com.fasterxml.jackson.annotation.JsonProperty;
import com.resolveflow.caseservice.casefile.CaseEvidenceService;
import com.resolveflow.caseservice.casefile.CaseRepository;
import com.resolveflow.caseservice.casefile.CaseRow;
import com.resolveflow.caseservice.casefile.EvidenceRepository;
import java.util.ArrayList;
import java.util.List;
import org.springframework.http.MediaType;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

/**
 * {@code GET /internal/v1/cases/{case_id}/evidence}: what the case holds, for the Agent's run (C06.4⑤).
 *
 * <p>Declared in {@code contracts/core/openapi-case.yaml} since C00 and, until this slice, implemented nowhere —
 * the same gap C06.2c found for {@code refund-status}, and invisible for the same reason: the Python tool that
 * needs it is only tested against a stub, and a stub answers whatever it is told to, so a read of a route nobody
 * serves looks exactly like a read of a working one. It was found by asking which routes the five tools actually
 * need and grepping the Java for them.
 *
 * <p><b>Why this is not the public {@code GET /api/v1/cases/{case_id}} projection.</b> That route returns a form
 * built for a reviewer: material with its text, who appended it and at which revision. A run needs the
 * <em>reference</em> form — {@code observation_id}, {@code source_ref}, {@code source_version},
 * {@code content_hash} — because a reference is what a proposal cites and what Java later re-checks
 * ({@code docs/core-contracts.md:61}). Serving the reviewer view here would hand the Agent a document to quote
 * instead of a citation to verify, and {@code EvidenceRef} deliberately carries no text for the same reason.
 *
 * <p><b>{@code source_version} is the revision the material was appended at</b>, read from the record rather than
 * re-derived from the case. Re-deriving it would make every historical record claim to be current, which is
 * precisely the staleness a citation check exists to catch. The answer's own {@code input_revision} is where the
 * case is <em>now</em>, so a run that cited revision 2 can see that the case has moved to 3.
 *
 * <p><b>An empty case answers an empty list, not a 404.</b> "This case holds nothing" is an answer; a 404 would
 * say the case does not exist, and the Agent would record {@code NOT_FOUND} — which
 * {@code docs/agent-spec.md:36} is explicit is not a negative fact. Only an unknown case is 404.
 */
@RestController
@RequestMapping("/internal/v1/cases")
public class CaseEvidenceInternalController {

    private final EvidenceRepository evidence;
    private final CaseRepository cases;

    public CaseEvidenceInternalController(EvidenceRepository evidence, CaseRepository cases) {
        this.evidence = evidence;
        this.cases = cases;
    }

    /** The contract's {@code EvidenceListResponse}. All three members are required. */
    public record EvidenceListResponse(
            @JsonProperty("case_id") String caseId,
            @JsonProperty("input_revision") int inputRevision,
            @JsonProperty("evidence") List<EvidenceRef> evidence) {}

    /** The contract's {@code EvidenceRef}: a controlled reference, never a requestable address. */
    public record EvidenceRef(
            @JsonProperty("observation_id") String observationId,
            @JsonProperty("source_ref") String sourceRef,
            @JsonProperty("source_version") String sourceVersion,
            @JsonProperty("content_hash") String contentHash) {}

    /** No such case. A case that holds nothing is a 200 with an empty list. */
    public static class CaseEvidenceNotFoundException extends RuntimeException {

        private static final long serialVersionUID = 1L;

        public CaseEvidenceNotFoundException(String message) {
            super(message);
        }
    }

    @GetMapping(path = "/{case_id}/evidence", produces = MediaType.APPLICATION_JSON_VALUE)
    public ResponseEntity<EvidenceListResponse> read(@PathVariable("case_id") String caseId) {
        CaseRow row = cases.findCase(caseId);
        if (row == null) {
            throw new CaseEvidenceNotFoundException("no such case");
        }
        // Newest-first from the query and reversed here, exactly as the reviewer projection does it: the cap
        // keeps the most recent material rather than an arbitrary prefix of the oldest, and `findRecent` is the
        // one statement that decides what "a case's material" means.
        List<EvidenceRepository.EvidenceRow> newestFirst = evidence.findRecent(caseId, CaseEvidenceService.MAX_RECORDS);
        List<EvidenceRef> oldestFirst = new ArrayList<>(newestFirst.size());
        for (int index = newestFirst.size() - 1; index >= 0; index--) {
            oldestFirst.add(of(newestFirst.get(index)));
        }
        return ResponseEntity.ok(new EvidenceListResponse(row.caseId(), row.inputRevision(), oldestFirst));
    }

    private static EvidenceRef of(EvidenceRepository.EvidenceRow stored) {
        // `evidence_id` is the store's name for what the wire calls `observation_id`. They are the same value —
        // the run's stable id for one observation — and the field is renamed at this boundary rather than stored
        // twice, because two columns holding one id is how they start disagreeing.
        return new EvidenceRef(stored.evidenceId(), stored.sourceRef(), stored.sourceVersion(), stored.contentHash());
    }
}
