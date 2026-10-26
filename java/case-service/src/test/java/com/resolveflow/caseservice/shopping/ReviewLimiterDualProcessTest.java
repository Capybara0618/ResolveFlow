package com.resolveflow.caseservice.shopping;

import static org.assertj.core.api.Assertions.*;

import com.resolveflow.caseservice.CaseDatabaseTest;
import com.resolveflow.shared.security.*;
import com.sun.net.httpserver.HttpServer;
import java.net.*;
import java.net.http.*;
import java.nio.charset.StandardCharsets;
import java.nio.file.*;
import java.time.*;
import java.util.*;
import java.util.concurrent.*;
import java.util.concurrent.atomic.AtomicInteger;
import org.junit.jupiter.api.Test;
import org.springframework.jdbc.core.ConnectionCallback;
import org.testcontainers.containers.GenericContainer;
import tools.jackson.databind.ObjectMapper;

class ReviewLimiterDualProcessTest extends CaseDatabaseTest {
    static final ObjectMapper JSON = new ObjectMapper();
    final HttpClient http =
            HttpClient.newBuilder().connectTimeout(Duration.ofSeconds(2)).build();
    final List<Process> processes = new ArrayList<>();
    final List<Integer> ports = new ArrayList<>();
    Path folder;

    record Identity(String token, String path, String body) {}

    Identity identity(String username, String buyer) {
        var role = buyer == null ? Role.MERCHANT_ADMIN : Role.CUSTOMER;
        var principal = new AuthenticatedPrincipal(username, buyer == null ? "M-1001" : null, role, null, buyer);
        String token = new JwtCodec("resolveflow-core-demo-identity-secret", Duration.ofMinutes(10))
                .issue(principal, Instant.now());
        return new Identity(
                token,
                buyer == null
                        ? "/api/v1/merchant/reviews/1/reply"
                        : "/api/v1/shop/orders/lines/D4-limiter-fixture/review",
                buyer == null
                        ? "{\"body\":\"synthetic reply\",\"expected_version\":1}"
                        : "{\"rating\":3,\"body\":\"synthetic write\",\"expected_version\":0}");
    }

    void save(String name, Object value) throws Exception {
        Files.writeString(
                folder.resolve(name + ".json"), JSON.writeValueAsString(value), StandardOpenOption.CREATE_NEW);
    }

    Map<String, Object> post(int node, Identity identity) throws Exception {
        long at = System.nanoTime();
        var response = http.send(
                HttpRequest.newBuilder(URI.create("http://127.0.0.1:" + ports.get(node) + identity.path()))
                        .timeout(Duration.ofSeconds(5))
                        .header("Authorization", "Bearer " + identity.token())
                        .header("Content-Type", "application/json")
                        .POST(HttpRequest.BodyPublishers.ofString(identity.body()))
                        .build(),
                HttpResponse.BodyHandlers.ofString());
        return Map.of(
                "node",
                node,
                "status",
                response.statusCode(),
                "elapsed_ms",
                (System.nanoTime() - at) / 1000000.0,
                "body",
                JSON.readTree(response.body()));
    }

    List<Map<String, Object>> burst(Identity who) throws Exception {
        try (var pool = Executors.newFixedThreadPool(12)) {
            var start = new CountDownLatch(1);
            var jobs = new ArrayList<Future<Map<String, Object>>>();
            for (int i = 0; i < 12; i++) {
                int node = i % 2;
                jobs.add(pool.submit(() -> {
                    start.await();
                    return post(node, who);
                }));
            }
            start.countDown();
            var rows = new ArrayList<Map<String, Object>>();
            for (var job : jobs) rows.add(job.get(10, TimeUnit.SECONDS));
            return rows;
        }
    }

    @Test
    void threeRealWindowsAcrossTwoCaseProcessesRejectBeforeDownstreamHttp() throws Exception {
        folder = Path.of(System.getProperty("resolveflow.d4.limiter", "target/d4-limiter-" + UUID.randomUUID()))
                .toAbsolutePath();
        Files.createDirectory(folder);
        registerTestAccount("d4-limit-merchant", "M-1001", "MERCHANT_ADMIN", null);
        registerTestAccount("d4-limit-other", "M-1001", "MERCHANT_ADMIN", null);
        var reply = identity("d4-limit-merchant", null);
        var write = identity("demo-buyer", "B-3001");
        var downstream = new AtomicInteger();
        var calls = Collections.synchronizedList(new ArrayList<Map<String, Object>>());
        var server = HttpServer.create(new InetSocketAddress("127.0.0.1", 0), 0);
        server.createContext("/internal/v1/", exchange -> {
            var body = new String(exchange.getRequestBody().readAllBytes(), StandardCharsets.UTF_8);
            new JwtCodec("resolveflow-core-demo-identity-secret", Duration.ofMinutes(10))
                    .verifyAsService(
                            exchange.getRequestHeaders()
                                    .getFirst("Authorization")
                                    .substring(7),
                            Instant.now());
            downstream.incrementAndGet();
            calls.add(Map.of("path", exchange.getRequestURI().getPath(), "body", JSON.readTree(body)));
            byte[] payload =
                    "{\"review_id\":1,\"product_id\":\"D4-fixture\",\"product_name\":\"synthetic\",\"variant\":\"fixture\",\"rating\":3,\"body\":\"synthetic write\",\"reply\":\"synthetic reply\",\"version\":2,\"created_at\":\"2026-10-26T00:00:00Z\",\"updated_at\":\"2026-10-26T00:00:00Z\"}"
                            .getBytes(StandardCharsets.UTF_8);
            exchange.getResponseHeaders().set("Content-Type", "application/json");
            exchange.sendResponseHeaders(200, payload.length);
            try (var output = exchange.getResponseBody()) {
                output.write(payload);
            }
        });
        server.start();
        try (var redis = new GenericContainer<>("redis:7.4-alpine").withExposedPorts(6379)) {
            redis.start();
            try {
                for (String node : List.of("a", "b")) {
                    var command = List.of(
                            Path.of(System.getProperty("java.home"), "bin", "java.exe")
                                    .toString(),
                            "-XX:ActiveProcessorCount=2",
                            "-Xms64m",
                            "-Xmx320m",
                            "-Drf.d4.lab=" + folder.getFileName(),
                            "-Drf.d4.directory=" + folder,
                            "-Drf.d4.node=" + node,
                            "-cp",
                            System.getProperty("surefire.test.class.path"),
                            ReviewLimiterLabProcess.class.getName(),
                            "--server.address=127.0.0.1",
                            "--server.port=0",
                            "--spring.datasource.url="
                                    + jdbc.execute((ConnectionCallback<String>)
                                            (c -> c.getMetaData().getURL())),
                            "--spring.datasource.username=case_svc",
                            "--spring.datasource.password=case_svc",
                            "--spring.data.redis.host=127.0.0.1",
                            "--spring.data.redis.port=" + redis.getMappedPort(6379),
                            "--resolveflow.commerce.base-url=http://127.0.0.1:"
                                    + server.getAddress().getPort(),
                            "--resolveflow.product-reviews.rate-limit-enabled=true",
                            "--resolveflow.dispatch.enabled=false",
                            "--resolveflow.support-agent.enabled=false");
                    var process = new ProcessBuilder(command)
                            .redirectErrorStream(true)
                            .redirectOutput(folder.resolve(node + ".log").toFile())
                            .start();
                    processes.add(process);
                    long deadline = System.nanoTime() + TimeUnit.SECONDS.toNanos(60);
                    Path ready = folder.resolve(node + ".ready");
                    while (!Files.exists(ready) && System.nanoTime() < deadline) {
                        assertThat(process.isAlive()).isTrue();
                        Thread.sleep(20);
                    }
                    assertThat(Files.exists(ready)).isTrue();
                    ports.add(
                            JSON.readTree(Files.readString(ready)).path("port").asInt());
                }
                var windows = new ArrayList<Map<String, Object>>();
                for (int window = 0; window < 3; window++) {
                    if (window > 0) Thread.sleep(61000);
                    int begin = downstream.get();
                    var replyRows = burst(reply);
                    var writeRows = burst(write);
                    for (var rows : List.of(replyRows, writeRows)) {
                        assertThat(rows.stream()
                                        .filter(r -> r.get("status").equals(200))
                                        .count())
                                .isEqualTo(6);
                        assertThat(rows.stream()
                                        .filter(r -> r.get("status").equals(429))
                                        .count())
                                .isEqualTo(6);
                    }
                    assertThat(downstream.get() - begin).isEqualTo(12);
                    var row = Map.of(
                            "window",
                            window,
                            "reply",
                            replyRows,
                            "write",
                            writeRows,
                            "downstream_http_calls",
                            downstream.get() - begin);
                    save("window-" + window, row);
                    windows.add(row);
                }
                assertThat(post(0, identity("d4-limit-other", null)).get("status"))
                        .isEqualTo(200);
                int begin = downstream.get();
                redis.execInContainer("redis-cli", "CLIENT", "PAUSE", "10000");
                Map<String, Object> unavailable;
                try {
                    unavailable = post(1, identity("d4-limit-other", null));
                    assertThat(unavailable.get("status")).isEqualTo(503);
                    assertThat(downstream.get()).isEqualTo(begin);
                } finally {
                    redis.execInContainer("redis-cli", "CLIENT", "UNPAUSE");
                }
                assertThat(post(0, identity("d4-limit-other", null)).get("status"))
                        .isEqualTo(200);
                save(
                        "summary",
                        Map.of(
                                "status",
                                "PASSED",
                                "windows",
                                windows,
                                "unavailable",
                                unavailable,
                                "downstream_http_calls",
                                downstream.get(),
                                "calls",
                                calls,
                                "pids",
                                processes.stream().map(Process::pid).toList(),
                                "boundary",
                                "real two Case JVMs / Redis / production auth and Controller; explicitly simulated Commerce HTTP response, not actual review DB writes"));
            } catch (Throwable error) {
                save("failure", Map.of("error", error.toString(), "downstream", downstream.get()));
                throw error;
            } finally {
                for (var p : processes) {
                    p.destroyForcibly();
                    assertThat(p.waitFor(10, TimeUnit.SECONDS)).isTrue();
                }
            }
        } finally {
            server.stop(0);
        }
    }
}
