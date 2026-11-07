package com.resolveflow.commerce.catalog;

import com.resolveflow.commerce.CommerceServiceApplication;
import io.micrometer.core.instrument.MeterRegistry;
import java.nio.file.*;
import java.time.Instant;
import java.util.*;
import org.aopalliance.intercept.MethodInterceptor;
import org.springframework.aop.framework.Advised;
import org.springframework.boot.SpringApplication;
import org.springframework.boot.test.context.TestConfiguration;
import org.springframework.context.annotation.Bean;
import org.springframework.web.servlet.function.*;
import tools.jackson.databind.ObjectMapper;

/** Explicit test-classpath process only; no fault route or gate is packaged in production. */
public final class ReviewCacheLabProcess {
    static final ObjectMapper JSON = new ObjectMapper();
    static Path directory;
    static String node;

    static synchronized void event(Map<String, Object> value) throws Exception {
        var record = new LinkedHashMap<>(value);
        record.put("node", node);
        record.put("pid", ProcessHandle.current().pid());
        record.put("at", Instant.now().toString());
        Files.writeString(
                directory.resolve(node + "-events.jsonl"),
                JSON.writeValueAsString(record) + "\n",
                StandardOpenOption.CREATE,
                StandardOpenOption.APPEND);
    }

    public static void main(String[] args) throws Exception {
        directory = Path.of(System.getProperty("rf.d4.directory")).toAbsolutePath();
        node = System.getProperty("rf.d4.node");
        if (!Files.isDirectory(directory) || !node.matches("[ab]"))
            throw new IllegalArgumentException("owned fixture directory and node required");
        var context = SpringApplication.run(new Class<?>[] {CommerceServiceApplication.class, Probe.class}, args);
        var reviews = context.getBean(ProductReviewService.class);
        ((Advised) reviews).addAdvice(0, (MethodInterceptor) invocation -> {
            if (!invocation.getMethod().getName().equals("publicPage")) return invocation.proceed();
            String product = (String) invocation.getArguments()[0];
            String call = UUID.randomUUID().toString();
            event(Map.of("stage", "page_start", "call", call, "product", product));
            try {
                Object result = invocation.proceed();
                if (org.springframework.transaction.support.TransactionSynchronizationManager
                        .isActualTransactionActive()) throw new AssertionError("probe holds business transaction");
                Path gate = directory.resolve("gate.json");
                if (Files.exists(gate)) {
                    var spec = JSON.readTree(Files.readString(gate));
                    if (product.equals(spec.path("product").asString())) {
                        String id = spec.path("id").asString();
                        Path entered = directory.resolve(node + "-" + id + ".entered");
                        Files.writeString(entered, call);
                        event(Map.of("stage", "snapshot_ready", "call", call, "product", product, "id", id));
                        if (spec.path("mode").asString().equals("fail"))
                            throw new org.springframework.dao.TransientDataAccessResourceException(
                                    "explicit lab post-query failure");
                        long deadline = System.nanoTime() + java.util.concurrent.TimeUnit.SECONDS.toNanos(20);
                        while (!Files.exists(directory.resolve(node + "-" + id + ".release"))) {
                            if (System.nanoTime() > deadline) throw new AssertionError("fixture gate expired");
                            Thread.sleep(5);
                        }
                    }
                }
                return result;
            } finally {
                event(Map.of("stage", "page_end", "call", call, "product", product));
            }
        });
        // Warm both Redis clients on a non-business key before experimental windows.
        long warmDeadline = System.nanoTime() + java.util.concurrent.TimeUnit.SECONDS.toNanos(10);
        while (true) {
            try {
                context.getBean(org.springframework.data.redis.core.StringRedisTemplate.class)
                        .opsForValue()
                        .get("d4-connection-warmup");
                var clients = context.getBeanProvider(org.redisson.api.RedissonClient.class);
                if (clients.getIfAvailable() != null) {
                    var lock = clients.getObject().getLock("d4-probe-warmup-" + node);
                    lock.lock(1, java.util.concurrent.TimeUnit.SECONDS);
                    lock.unlock();
                }
                break;
            } catch (RuntimeException startup) {
                event(Map.of(
                        "stage",
                        "warmup_retry",
                        "error_type",
                        startup.getClass().getSimpleName()));
                if (System.nanoTime() > warmDeadline) {
                    context.close();
                    throw startup;
                }
                Thread.sleep(100);
            }
        }
        int port = ((org.springframework.boot.web.server.context.WebServerApplicationContext) context)
                .getWebServer()
                .getPort();
        Path ready = directory.resolve(node + ".ready");
        Path pending = directory.resolve(node + ".ready.tmp");
        Files.writeString(
                pending,
                JSON.writeValueAsString(
                        Map.of("port", port, "pid", ProcessHandle.current().pid())),
                StandardOpenOption.CREATE_NEW);
        Files.move(pending, ready, StandardCopyOption.ATOMIC_MOVE);
    }

    @TestConfiguration(proxyBeanMethods = false)
    static class Probe {
        @Bean
        RouterFunction<ServerResponse> d4Metrics(MeterRegistry registry) {
            return RouterFunctions.route()
                    .GET("/__d4/metrics", request -> {
                        var values = new TreeMap<String, Double>();
                        for (var meter : registry.getMeters()) {
                            String name = meter.getId().getName();
                            if (!name.startsWith("resolveflow.product_reviews")) continue;
                            String suffix = meter.getId().getTags().toString();
                            for (var measurement : meter.measure())
                                values.put(name + suffix + ":" + measurement.getStatistic(), measurement.getValue());
                        }
                        return ServerResponse.ok().body(values);
                    })
                    .build();
        }
    }
}
