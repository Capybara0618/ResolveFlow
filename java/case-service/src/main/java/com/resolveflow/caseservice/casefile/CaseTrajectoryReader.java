package com.resolveflow.caseservice.casefile;

import java.util.List;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

/**
 * The status and the trajectory of a case, read as one consistent view.
 *
 * <p>They belong together because they commit together: cancelling a case writes the terminal status and
 * its closing event in one transaction. Reading them separately let the stream observe a status that was
 * already terminal while its earlier read of the trajectory had not yet seen the closing event, so the
 * stream completed without ever sending it — the subscriber's last frame was the material append, and the
 * case simply stopped. The live stream test caught that; this class is the fix, and the reason it is a
 * class rather than a method is that {@code @Transactional} only applies across a proxy boundary.
 *
 * <p>One snapshot for both reads is what makes completion safe: a tick either sees a live case (and keeps
 * streaming) or sees the ending and the events that explain it, never one without the other.
 */
@Service
public class CaseTrajectoryReader {

    private final CaseRepository cases;

    public CaseTrajectoryReader(CaseRepository cases) {
        this.cases = cases;
    }

    @Transactional(readOnly = true)
    public CaseTrajectory read(String caseId, int afterSequence) {
        CaseRow row = cases.findCase(caseId);
        List<TimelineEventRow> events = cases.findTimelineAfter(caseId, afterSequence);
        return new CaseTrajectory(row == null ? null : row.status(), events);
    }

    /** A snapshot of where a case stands and what has happened since a sequence number. */
    public record CaseTrajectory(CaseStatus status, List<TimelineEventRow> events) {

        /** True when the case has ended, so nothing further can be appended to its trajectory. */
        public boolean ended() {
            return status != null && status.isTerminal();
        }
    }
}