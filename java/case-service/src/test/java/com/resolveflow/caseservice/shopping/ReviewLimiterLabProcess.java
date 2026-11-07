package com.resolveflow.caseservice.shopping;

import com.resolveflow.caseservice.CaseServiceApplication;
import java.nio.file.*;
import java.util.Map;
import java.util.concurrent.TimeUnit;
import org.springframework.boot.SpringApplication;
import org.springframework.data.redis.core.StringRedisTemplate;
import tools.jackson.databind.ObjectMapper;

/** Starts an actual Case application on loopback; test main is never packaged in the app jar. */
public final class ReviewLimiterLabProcess {
    public static void main(String[] args) throws Exception {
        Path directory = Path.of(System.getProperty("rf.d4.directory")).toAbsolutePath();
        String node = System.getProperty("rf.d4.node");
        if (!Files.isDirectory(directory) || !node.matches("[ab]"))
            throw new IllegalArgumentException("explicit owned lab required");
        var context = SpringApplication.run(CaseServiceApplication.class, args);
        long deadline = System.nanoTime() + TimeUnit.SECONDS.toNanos(10);
        while (true) {
            try {
                context.getBean(StringRedisTemplate.class).opsForValue().get("d4-limiter-warmup");
                break;
            } catch (RuntimeException unavailable) {
                if (System.nanoTime() > deadline) {
                    context.close();
                    throw unavailable;
                }
                Thread.sleep(100);
            }
        }
        int port = ((org.springframework.boot.web.server.context.WebServerApplicationContext) context)
                .getWebServer()
                .getPort();
        Path pending = directory.resolve(node + ".ready.tmp");
        Files.writeString(
                pending,
                new ObjectMapper()
                        .writeValueAsString(Map.of(
                                "port", port, "pid", ProcessHandle.current().pid())),
                StandardOpenOption.CREATE_NEW);
        Files.move(pending, directory.resolve(node + ".ready"), StandardCopyOption.ATOMIC_MOVE);
    }
}
