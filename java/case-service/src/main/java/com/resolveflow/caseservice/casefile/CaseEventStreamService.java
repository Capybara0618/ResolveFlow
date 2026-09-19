package com.resolveflow.caseservice.casefile;

import com.resolveflow.shared.security.AuthenticatedPrincipal;
import com.resolveflow.shared.security.Role;
import java.io.IOException;
import java.time.Duration;
import java.util.List;
import java.util.concurrent.Executors;
import java.util.concurrent.ScheduledExecutorService;
import java.util.concurrent.ScheduledFuture;
import java.util.concurrent.TimeUnit;
import org.springframework.stereotype.Service;
import org.springframework.web.servlet.mvc.method.annotation.SseEmitter;
import tools.jackson.databind.ObjectMapper;

/**
 * The event stream for one case (docs/core-contracts.md:32).
 *
 * <p>Two decisions are worth stating because they are visible to a client:
 *
 * <ol>
 *   <li><b>Replay then push, as one code path.</b> A subscription first sends what already happened, in
 *       order, then keeps sending what happens next. Both come from {@code case_timeline}, so a client that
 *       subscribes late sees the same trajectory as one that subscribed early — the stream is not a
 *       separate source of truth that could disagree with the case view.
 *   <li><b>Resumption is by {@code Last-Event-ID}, and an id this case never issued means "from the
 *       beginning".</b> The alternative — refusing — would leave the client with nothing to do about it,
 *       while replaying is a superset of what it is missing. The choice is announced to the client as a
 *       comment, so a resumed stream that restarted says so instead of looking like an ordinary resume.
 * </ol>
 *
 * <p>The stream ends when the case does: after the last event of a terminal case is flushed, the response
 * completes rather than waiting for an event that can no longer happen. A timeout (10 minutes) and a
 * heartbeat (15 seconds) bound the connection from the other side, so a client that walked away does not
 * hold a slot forever.
 *
 * <p>The token never appears in the URL (docs/core-contracts.md:32), which is why the principal is resolved
 * before the response begins and a refusal is an ordinary error response rather than a stream that starts
 * and then apologises.
 */
@Service
public class CaseEventStreamService {

    private static final long STREAM_TIMEOUT_MS = Duration.ofMinutes(10).toMillis();
    private static final long POLL_INTERVAL_MS = Duration.ofSeconds(1).toMillis();
    private static final long HEARTBEAT_INTERVAL_MS = Duration.ofSeconds(15).toMillis();

    private final CaseRepository cases;
    private final CaseTrajectoryReader trajectory;
    private final ObjectMapper mapper;
    private final ScheduledExecutorService scheduler = Executors.newScheduledThreadPool(2, runnable -> {
        Thread thread = new Thread(runnable, "case-event-stream");
        thread.setDaemon(true);
        return thread;
    });

    public CaseEventStreamService(CaseRepository cases, CaseTrajectoryReader trajectory, ObjectMapper mapper) {
        this.cases = cases;
        this.trajectory = trajectory;
        this.mapper = mapper;
    }

    /**
     * Opens the stream, or refuses before it starts.
     *
     * <p>Visibility is checked here, before any emitter exists: a case the principal cannot see is answered
     * like one that does not exist, and the answer is the same error body every other route gives.
     */
    public SseEmitter stream(AuthenticatedPrincipal principal, String caseId, String lastEventId) {
        CaseRow row = cases.findCase(caseId);
        if (row == null || !visibleTo(principal, row)) {
            throw new CaseReadService.CaseNotVisibleException();
        }
        SseEmitter emitter = new SseEmitter(STREAM_TIMEOUT_MS);
        Stream stream = new Stream(emitter, caseId, lastEventId);
        emitter.onCompletion(stream::stop);
        emitter.onTimeout(stream::stop);
        emitter.onError(error -> stream.stop());
        stream.schedule();
        return emitter;
    }

    private static boolean visibleTo(AuthenticatedPrincipal principal, CaseRow row) {
        if (!row.merchantId().equals(principal.merchantId())) {
            return false;
        }
        return principal.role() != Role.CUSTOMER || row.customerId().equals(principal.customerId());
    }

    /**
     * One subscription.
     *
     * <p>The first tick replays and every later tick polls, both by asking for events after a sequence
     * number. That is deliberate: replay is not a special case with its own logic, it is the same read with
     * the sequence number starting at zero.
     */
    private final class Stream implements Runnable {

        private final SseEmitter emitter;
        private final String caseId;
        private final String lastEventId;
        private volatile boolean stopped;
        private volatile ScheduledFuture<?> future;
        private int cursor;
        private boolean started;
        private long lastFrameAt;

        Stream(SseEmitter emitter, String caseId, String lastEventId) {
            this.emitter = emitter;
            this.caseId = caseId;
            this.lastEventId = lastEventId;
            this.lastFrameAt = System.currentTimeMillis();
        }

        void schedule() {
            future = scheduler.scheduleWithFixedDelay(this, 0, POLL_INTERVAL_MS, TimeUnit.MILLISECONDS);
        }

        void stop() {
            stopped = true;
            ScheduledFuture<?> scheduled = future;
            if (scheduled != null) {
                scheduled.cancel(false);
            }
        }

        @Override
        public void run() {
            if (stopped) {
                return;
            }
            try {
                if (!started) {
                    started = true;
                    resolveCursor();
                }
                // The status and the events come from one snapshot: a case that ends does so in the
                // same transaction as the event that explains it, so seeing one means seeing the other.
                CaseTrajectoryReader.CaseTrajectory snapshot = trajectory.read(caseId, cursor);
                List<TimelineEventRow> pending = snapshot.events();
                for (TimelineEventRow event : pending) {
                    send(event);
                    cursor = event.sequence();
                }
                if (!pending.isEmpty()) {
                    lastFrameAt = System.currentTimeMillis();
                }
                if (snapshot.ended()) {
                    // Nothing more can happen to this case, so the stream ends instead of idling.
                    emitter.complete();
                    stop();
                    return;
                }
                // Quiet periods are kept alive: a proxy or a browser will drop a stream that sends
                // nothing, and a heartbeat is a comment so it can never be mistaken for an event.
                if (System.currentTimeMillis() - lastFrameAt > HEARTBEAT_INTERVAL_MS) {
                    emitter.send(SseEmitter.event().comment("keep-alive"));
                    lastFrameAt = System.currentTimeMillis();
                }
            } catch (IOException | IllegalStateException disconnected) {
                // The client went away; the emitter is finished with and there is nothing to report.
                stop();
            } catch (RuntimeException error) {
                stop();
                emitter.completeWithError(error);
            }
        }

        /**
         * Where a subscription starts.
         *
         * <p>An unknown id is not an error: it means the client cannot be resumed, so the stream starts at
         * the beginning and says so in a comment. The comment is not an event, so a client cannot mistake it
         * for something that happened to the case.
         */
        private void resolveCursor() throws IOException {
            if (lastEventId == null || lastEventId.isBlank()) {
                cursor = 0;
                return;
            }
            Integer sequence = cases.findSequenceByEventId(caseId, lastEventId);
            if (sequence == null) {
                cursor = 0;
                emitter.send(SseEmitter.event().comment("unknown Last-Event-ID; replaying from the beginning"));
                return;
            }
            cursor = sequence;
        }

        private void send(TimelineEventRow event) throws IOException {
            String data = mapper.writeValueAsString(TimelineEventView.of(event));
            emitter.send(SseEmitter.event()
                    .id(event.eventId())
                    .name(event.kind().name())
                    .data(data));
        }
    }
}
