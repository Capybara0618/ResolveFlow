package com.resolveflow.caseservice.support;

import com.resolveflow.caseservice.order.RequestPrincipalResolver;
import jakarta.annotation.PreDestroy;
import java.io.IOException;
import java.util.Set;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.Executors;
import java.util.concurrent.ScheduledFuture;
import java.util.concurrent.TimeUnit;
import org.springframework.stereotype.Service;
import org.springframework.web.servlet.mvc.method.annotation.SseEmitter;

/** Authenticated, read-only consultation subscriptions. Reconnection never dispatches an Agent. */
@Service
public class SupportEventStreamService {
    private final SupportService support;
    private final SupportStreamEvents events;
    private final RequestPrincipalResolver principals;
    private final java.util.concurrent.ScheduledExecutorService scheduler = Executors.newScheduledThreadPool(
            2, Thread.ofPlatform().name("support-event-stream-", 0).daemon().factory());
    private final Set<Stream> streams = ConcurrentHashMap.newKeySet();

    public SupportEventStreamService(
            SupportService support, SupportStreamEvents events, RequestPrincipalResolver principals) {
        this.support = support;
        this.events = events;
        this.principals = principals;
    }

    private com.resolveflow.shared.support.SupportWire.Conversation visible(String auth, String id) {
        var session = principals.session(auth);
        if (!session.principal().isPlatformBuyer()) throw new SupportService.Refused(404, "NOT_FOUND", "咨询不存在");
        return support.read(session, id, null);
    }

    public SseEmitter stream(String auth, String conversation, String lastId) {
        visible(auth, conversation); // Refuse before headers/any private frame are sent.
        Long cursor = null;
        try {
            if (lastId != null && lastId.matches("[0-9]{1,19}")) cursor = Long.parseLong(lastId);
        } catch (NumberFormatException ignored) {
            // Unknown cursor resumes from a snapshot, never from a different conversation.
        }
        var emitter = new SseEmitter(600_000L);
        var stream = new Stream(emitter, auth, conversation, cursor);
        streams.add(stream);
        emitter.onCompletion(stream::stop);
        emitter.onTimeout(() -> {
            stream.stop();
            emitter.complete();
        });
        emitter.onError(error -> stream.stop());
        stream.future = scheduler.scheduleWithFixedDelay(stream, 0, 250, TimeUnit.MILLISECONDS);
        if (stream.stopped) stream.future.cancel(false);
        return emitter;
    }

    private final class Stream implements Runnable {
        final SseEmitter emitter;
        final String auth, conversation;
        Long cursor;
        volatile boolean stopped;
        volatile ScheduledFuture<?> future;
        boolean connected;
        long lastSent = System.nanoTime();

        Stream(SseEmitter emitter, String auth, String conversation, Long cursor) {
            this.emitter = emitter;
            this.auth = auth;
            this.conversation = conversation;
            this.cursor = cursor;
        }

        void stop() {
            stopped = true;
            if (future != null) future.cancel(false);
            streams.remove(this);
        }

        @Override
        public void run() {
            if (stopped) return;
            try {
                var frames = events.read(conversation, cursor, () -> visible(auth, conversation));
                if (!connected) {
                    emitter.send(SseEmitter.event().comment("connected"));
                    connected = true;
                }
                for (var frame : frames) {
                    emitter.send(SseEmitter.event()
                            .id(Long.toString(frame.id()))
                            .name(frame.kind())
                            .data(frame.data()));
                    cursor = frame.id();
                    lastSent = System.nanoTime();
                }
                if (System.nanoTime() - lastSent >= TimeUnit.SECONDS.toNanos(15)) {
                    emitter.send(SseEmitter.event().comment("keep-alive"));
                    lastSent = System.nanoTime();
                }
            } catch (SupportService.Refused | RequestPrincipalResolver.UnauthenticatedException revoked) {
                stop();
                emitter.complete();
            } catch (IOException | IllegalStateException disconnected) {
                stop();
            } catch (RuntimeException refused) {
                stop();
                emitter.completeWithError(refused);
            }
        }
    }

    @PreDestroy
    public void close() {
        for (Stream stream : streams) {
            stream.stop();
            stream.emitter.complete();
        }
        scheduler.shutdownNow();
    }
}
