package com.resolveflow.commerce.catalog;

import static org.assertj.core.api.Assertions.*;

import com.resolveflow.commerce.CommerceDatabaseTest;
import com.resolveflow.shared.security.*;
import com.resolveflow.shared.shopping.CheckoutWire.*;
import com.resolveflow.shared.shopping.ProductReviewWire.*;
import com.resolveflow.shared.shopping.ShoppingWire.*;
import java.net.URI;
import java.net.http.*;
import java.nio.file.*;
import java.time.*;
import java.util.*;
import java.util.concurrent.*;
import java.util.function.BooleanSupplier;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.jdbc.core.JdbcTemplate;
import org.testcontainers.containers.GenericContainer;
import tools.jackson.databind.ObjectMapper;

/** Two independently started Commerce JVMs; production HTTP/controllers/cache/SQL/Redis, owned disposable data. */
class ReviewCacheDualProcessTest extends CommerceDatabaseTest {
    @Autowired
    JdbcTemplate jdbc;

    @Autowired
    ShoppingService shop;

    @Autowired
    CheckoutPayments payments;

    @Autowired
    ProductReviewService reviews;

    static final ObjectMapper JSON = new ObjectMapper();
    static final String SECRET = "resolveflow-core-demo-identity-secret";
    final HttpClient http =
            HttpClient.newBuilder().connectTimeout(Duration.ofSeconds(2)).build();
    Path directory;
    GenericContainer<?> redis;
    final Map<String, Process> children = new HashMap<>();
    final Map<String, Integer> ports = new HashMap<>();
    final List<Map<String, Object>> outcomes = new ArrayList<>();
    String condition;
    final List<String> fixtureProducts = new ArrayList<>();

    record Fixture(String product, String line, long review) {}

    static void waitFor(String label, BooleanSupplier ready, int seconds) throws Exception {
        long deadline = System.nanoTime() + TimeUnit.SECONDS.toNanos(seconds);
        while (System.nanoTime() < deadline) {
            if (ready.getAsBoolean()) return;
            Thread.sleep(10);
        }
        throw new AssertionError("not reached: " + label);
    }

    void save(String name, Object value) throws Exception {
        Files.writeString(
                directory.resolve(name + ".json"), JSON.writeValueAsString(value), StandardOpenOption.CREATE_NEW);
    }

    void start(String node, boolean locking) throws Exception {
        Path ready = directory.resolve(node + ".ready");
        Files.deleteIfExists(ready);
        String java =
                Path.of(System.getProperty("java.home"), "bin", "java.exe").toString();
        var command = new ArrayList<>(List.of(
                java,
                "-XX:ActiveProcessorCount=2",
                "-Xms64m",
                "-Xmx320m",
                "-Drf.d4.lab=" + directory.getFileName(),
                "-Drf.d4.directory=" + directory,
                "-Drf.d4.node=" + node,
                "-cp",
                System.getProperty("surefire.test.class.path"),
                ReviewCacheLabProcess.class.getName(),
                "--server.address=127.0.0.1",
                "--server.port=0",
                "--spring.datasource.url="
                        + jdbc.execute((org.springframework.jdbc.core.ConnectionCallback<String>)
                                (connection -> connection.getMetaData().getURL())),
                "--spring.datasource.username=" + "commerce",
                "--spring.datasource.password=" + "commerce",
                "--spring.data.redis.host=127.0.0.1",
                "--spring.data.redis.port=" + redis.getMappedPort(6379),
                "--resolveflow.product-reviews.cache-enabled=true",
                "--resolveflow.product-reviews.rebuild-lock-enabled=" + locking,
                "--resolveflow.product-reviews.cache-namespace=d4:" + directory.getFileName() + ":" + condition,
                "--logging.level.com.resolveflow.commerce.catalog.ProductReviewReadCache=DEBUG"));
        var builder = new ProcessBuilder(command)
                .redirectErrorStream(true)
                .redirectOutput(ProcessBuilder.Redirect.appendTo(
                        directory.resolve(node + ".log").toFile()));
        // Prevent inherited application environment from connecting to any original service.
        builder.environment()
                .keySet()
                .removeIf(k -> k.startsWith("RESOLVEFLOW_")
                        || k.startsWith("COMMERCE_")
                        || k.startsWith("REFUND_")
                        || k.startsWith("CHECKOUT_")
                        || k.startsWith("PRODUCT_REVIEW_"));
        var child = builder.start();
        children.put(node, child);
        waitFor(
                "Commerce " + node,
                () -> {
                    if (!child.isAlive()) throw new AssertionError("child exited: " + node);
                    return Files.exists(ready);
                },
                60);
        var value = JSON.readTree(Files.readString(ready));
        ports.put(node, value.path("port").asInt());
        assertThat(value.path("pid").asLong()).isEqualTo(child.pid());
        Files.writeString(
                directory.resolve("processes.jsonl"),
                JSON.writeValueAsString(Map.of(
                                "node", node, "pid", child.pid(), "condition", condition, "port", ports.get(node)))
                        + "\n",
                StandardOpenOption.CREATE,
                StandardOpenOption.APPEND);
    }

    void stop(String node) throws Exception {
        Process child = children.remove(node);
        if (child == null) return;
        child.destroyForcibly();
        assertThat(child.waitFor(10, TimeUnit.SECONDS)).isTrue();
    }

    Fixture fixture(String label) {
        String suffix = UUID.randomUUID().toString().substring(0, 8),
                product = "D4-" + suffix,
                sku = "D4-SKU-" + suffix,
                buyer = "D4-" + suffix;
        fixtureProducts.add(product);
        jdbc.update(
                "INSERT INTO catalog_product(product_id,store_id,name,description,category,asset_key,listed) SELECT ?,store_id,name,description,category,asset_key,listed FROM catalog_product WHERE product_id='P-1001'",
                product);
        jdbc.update(
                "INSERT INTO catalog_sku(sku_id,product_id,variant,unit_amount,max_quantity,version,listed) SELECT ?,?,variant,unit_amount,max_quantity,version,listed FROM catalog_sku WHERE sku_id='SKU-1001-BLACK'",
                sku,
                product);
        var draft = shop.create(
                new DraftCommand("M-1001", buyer, UUID.randomUUID().toString(), new DraftRequest(sku, 1, 1L)));
        var payment = payments.pay(
                draft.draftId(),
                new PayCommand("M-1001", buyer, UUID.randomUUID().toString()));
        jdbc.update(
                "UPDATE shipment SET status='DELIVERED',carrier_conclusion='DELIVERED',source_version=2 WHERE line_id=?",
                payment.lineId());
        var review = reviews.save(payment.lineId(), new Command("M-1001", buyer, new Write(3L, label, 0L)));
        return new Fixture(product, payment.lineId(), review.reviewId());
    }

    Map<String, Object> request(String node, String product) throws Exception {
        long begin = System.nanoTime();
        String token = new JwtCodec(SECRET, Duration.ofMinutes(10))
                .issueServiceToken("case-service", null, null, ServiceScopes.COMMERCE_READ, Instant.now());
        var response = http.send(
                HttpRequest.newBuilder(URI.create("http://127.0.0.1:" + ports.get(node) + "/internal/v1/shop/products/"
                                + product + "/reviews"))
                        .timeout(Duration.ofSeconds(10))
                        .header("Authorization", "Bearer " + token)
                        .GET()
                        .build(),
                HttpResponse.BodyHandlers.ofString());
        return Map.of(
                "node",
                node,
                "status",
                response.statusCode(),
                "body",
                JSON.readTree(response.body()),
                "elapsed_ms",
                (System.nanoTime() - begin) / 1000000.0);
    }

    Map<String, Object> metrics(String node) throws Exception {
        var response = http.send(
                HttpRequest.newBuilder(URI.create("http://127.0.0.1:" + ports.get(node) + "/__d4/metrics"))
                        .timeout(Duration.ofSeconds(3))
                        .GET()
                        .build(),
                HttpResponse.BodyHandlers.ofString());
        assertThat(response.statusCode()).isEqualTo(200);
        return JSON.readValue(response.body(), Map.class);
    }

    void gate(String id, String product, String mode) throws Exception {
        Files.writeString(
                directory.resolve("gate.json"),
                JSON.writeValueAsString(Map.of("id", id, "product", product, "mode", mode)));
    }

    void ungate(String node, String id) throws Exception {
        Files.writeString(directory.resolve(node + "-" + id + ".release"), "release");
    }

    void entered(String node, String id) throws Exception {
        waitFor("snapshot " + id, () -> Files.exists(directory.resolve(node + "-" + id + ".entered")), 5);
    }

    void record(String scenario, Fixture fixture, Map<String, Object> details) throws Exception {
        var row = new LinkedHashMap<String, Object>();
        row.put("scenario", scenario);
        row.put("condition", condition);
        row.put("fixture", fixture);
        row.putAll(details);
        row.put("metrics_a", metrics("a"));
        row.put("metrics_b", metrics("b"));
        save(condition + "-" + scenario, row);
        outcomes.add(row);
    }

    void failureRecovery(boolean locking) throws Exception {
        Fixture f = fixture("exception-" + condition);
        String id = "failure-" + condition;
        gate(id, f.product(), "fail");
        var failed = request("a", f.product());
        assertThat(failed.get("status")).isEqualTo(500);
        Files.delete(directory.resolve("gate.json"));
        var recovered = request("b", f.product());
        assertThat(recovered.get("status")).isEqualTo(200);
        record("R02", f, Map.of("failed", failed, "recovered", recovered));
    }

    void killedOwner(boolean locking) throws Exception {
        Fixture f = fixture("kill-" + condition);
        String id = "kill-" + condition;
        gate(id, f.product(), "hold");
        try (var pool = Executors.newSingleThreadExecutor()) {
            var owner = pool.submit(() -> request("a", f.product()));
            entered("a", id);
            long old = children.get("a").pid(), started = System.nanoTime();
            stop("a");
            Files.delete(directory.resolve("gate.json"));
            String ownerFailure;
            try {
                owner.get(5, TimeUnit.SECONDS);
                throw new AssertionError("killed HTTP unexpectedly completed");
            } catch (ExecutionException expected) {
                ownerFailure = expected.getCause().getClass().getSimpleName();
            }
            Map<String, Object> result = null;
            var attempts = new ArrayList<Map<String, Object>>();
            while (System.nanoTime() - started < TimeUnit.SECONDS.toNanos(5)) {
                result = request("b", f.product());
                attempts.add(result);
                if (result.get("status").equals(200)) break;
                assertThat(result.get("status")).isEqualTo(503);
                Thread.sleep(50);
            }
            assertThat(result).isNotNull();
            assertThat(result.get("status")).isEqualTo(200);
            double recovery = (System.nanoTime() - started) / 1000000.0;
            start("a", locking);
            record(
                    "R03",
                    f,
                    Map.of(
                            "old_pid",
                            old,
                            "new_pid",
                            children.get("a").pid(),
                            "owner_transport_failure",
                            ownerFailure,
                            "recovery_ms",
                            recovery,
                            "attempts",
                            attempts));
        }
    }

    void suspend(String node, boolean pause) throws Exception {
        Process owned = children.get(node);
        assertThat(owned.isAlive()).isTrue();
        String type = """
            using System; using System.Runtime.InteropServices; public class NativeD4 {
            [DllImport("kernel32.dll")] public static extern IntPtr OpenProcess(uint a,bool b,int c);
            [DllImport("kernel32.dll")] public static extern bool CloseHandle(IntPtr h);
            [DllImport("ntdll.dll")] public static extern int NtSuspendProcess(IntPtr h);
            [DllImport("ntdll.dll")] public static extern int NtResumeProcess(IntPtr h); }
            """;
        String script =
                "Add-Type -TypeDefinition '" + type + "'; $handle=[NativeD4]::OpenProcess(2048,$false," + owned.pid()
                        + "); if ($handle -eq [IntPtr]::Zero) { throw 'no owned process handle' }; try { $status=[NativeD4]::"
                        + (pause ? "NtSuspendProcess" : "NtResumeProcess")
                        + "($handle); if ($status -ne 0) { throw 'process operation failed' } } finally { [void][NativeD4]::CloseHandle($handle) }";
        var control = new ProcessBuilder(
                        "powershell",
                        "-NoProfile",
                        "-EncodedCommand",
                        Base64.getEncoder().encodeToString(script.getBytes(java.nio.charset.StandardCharsets.UTF_16LE)))
                .redirectErrorStream(true)
                .redirectOutput(ProcessBuilder.Redirect.appendTo(
                        directory.resolve("process-control.log").toFile()))
                .start();
        assertThat(control.waitFor(10, TimeUnit.SECONDS)).isTrue();
        assertThat(control.exitValue()).isZero();
    }

    void expiredOwner(boolean locking) throws Exception {
        Fixture f = fixture("lease-" + condition);
        String id = "lease-" + condition;
        gate(id, f.product(), "hold");
        try (var pool = Executors.newFixedThreadPool(2)) {
            var old = pool.submit(() -> request("a", f.product()));
            entered("a", id);
            suspend("a", true);
            boolean paused = true;
            try {
                Thread.sleep(2100);
                var next = pool.submit(() -> request("b", f.product()));
                entered("b", id);
                suspend("a", false);
                paused = false;
                ungate("a", id);
                assertThat(old.get(5, TimeUnit.SECONDS).get("status")).isEqualTo(200);
                var key = "d4:" + directory.getFileName() + ":" + condition + ":" + f.product() + ":"
                        + reviews.publicEpoch(f.product()) + ":rebuild";
                String exists = redis.execInContainer("redis-cli", "EXISTS", key)
                        .getStdout()
                        .trim();
                if (locking) assertThat(exists).isEqualTo("1");
                ungate("b", id);
                assertThat(next.get(5, TimeUnit.SECONDS).get("status")).isEqualTo(200);
                Files.delete(directory.resolve("gate.json"));
                record(
                        "R04",
                        f,
                        Map.of(
                                "actual_process_suspended",
                                true,
                                "pause_ms",
                                2100,
                                "new_owner_lock_after_old_return",
                                exists));
            } finally {
                if (paused) suspend("a", false);
                ungate("a", id);
                ungate("b", id);
            }
        }
    }

    void changedEpoch(boolean locking) throws Exception {
        Fixture f = fixture("epoch-" + condition);
        String id = "epoch-" + condition;
        long before = reviews.publicEpoch(f.product());
        gate(id, f.product(), "hold");
        try (var pool = Executors.newSingleThreadExecutor()) {
            var old = pool.submit(() -> request("a", f.product()));
            entered("a", id);
            reviews.reply(f.review(), new ReplyCommand("M-1001", new Reply("committed-new-reply", 1L)));
            assertThat(reviews.publicEpoch(f.product())).isEqualTo(before + 1);
            ungate("b", id);
            var fresh = request("b", f.product());
            assertThat(fresh.get("status")).isEqualTo(200);
            assertThat(fresh.get("body").toString()).contains("committed-new-reply");
            ungate("a", id);
            var prior = old.get(5, TimeUnit.SECONDS);
            assertThat(prior.get("body").toString()).doesNotContain("committed-new-reply");
            Files.delete(directory.resolve("gate.json"));
            var finalRead = request("b", f.product());
            assertThat(finalRead.get("body")).isEqualTo(fresh.get("body"));
            record(
                    "R05",
                    f,
                    Map.of(
                            "old_epoch",
                            before,
                            "new_epoch",
                            before + 1,
                            "old_response",
                            prior,
                            "new_response",
                            fresh,
                            "final_response",
                            finalRead));
        }
    }

    void redisTimeout(boolean locking) throws Exception {
        Fixture f = fixture("redis-timeout-" + condition);
        String id = "redis-timeout-" + condition;
        gate(id, f.product(), "hold");
        try (var pool = Executors.newFixedThreadPool(33)) {
            var owner = pool.submit(() -> request("a", f.product()));
            entered("a", id);
            redis.execInContainer("redis-cli", "CLIENT", "PAUSE", "10000");
            var burst = new ArrayList<Future<Map<String, Object>>>();
            for (int i = 0; i < 32; i++) {
                String node = i % 2 == 0 ? "a" : "b";
                burst.add(pool.submit(() -> request(node, f.product())));
            }
            try {
                waitFor(
                        "two local DB gates full",
                        () -> {
                            try {
                                return inflight(metrics("a")) == 8 && inflight(metrics("b")) == 8;
                            } catch (Exception e) {
                                throw new IllegalStateException(e);
                            }
                        },
                        3);
            } finally {
                ungate("a", id);
                ungate("b", id);
                redis.execInContainer("redis-cli", "CLIENT", "UNPAUSE");
            }
            var responses = new ArrayList<Map<String, Object>>();
            responses.add(owner.get(5, TimeUnit.SECONDS));
            for (var future : burst) responses.add(future.get(5, TimeUnit.SECONDS));
            assertThat(responses)
                    .allSatisfy(row -> assertThat(row.get("status")).isIn(200, 503));
            Files.delete(directory.resolve("gate.json"));
            assertThat(inflight(metrics("a"))).isZero();
            assertThat(inflight(metrics("b"))).isZero();
            var recovered = request("b", f.product());
            assertThat(recovered.get("status")).isEqualTo(200);
            record("R06-timeout", f, Map.of("responses", responses, "recovered", recovered));
        }
    }

    static double inflight(Map<String, Object> values) {
        return values.entrySet().stream()
                .filter(e -> e.getKey().startsWith("resolveflow.product_reviews.database.inflight"))
                .mapToDouble(e -> ((Number) e.getValue()).doubleValue())
                .findFirst()
                .orElse(0);
    }

    @AfterEach
    void cleanOnlyOwnDisposableFixtures() {
        for (String product : fixtureProducts) {
            var drafts =
                    jdbc.queryForList("SELECT draft_id FROM checkout_draft WHERE product_id=?", String.class, product);
            var orders = jdbc.queryForList(
                    "SELECT DISTINCT l.order_id FROM order_line l JOIN catalog_sku k ON k.sku_id=l.sku WHERE k.product_id=?",
                    String.class,
                    product);
            jdbc.update("DELETE FROM product_review WHERE product_id=?", product);
            jdbc.update("DELETE FROM product_review_epoch WHERE product_id=?", product);
            for (String draft : drafts) {
                jdbc.update(
                        "DELETE FROM simulated_checkout_receipt WHERE attempt_id IN (SELECT attempt_id FROM checkout_payment_attempt WHERE draft_id=?)",
                        draft);
                jdbc.update(
                        "DELETE FROM checkout_payment_line WHERE attempt_id IN (SELECT attempt_id FROM checkout_payment_attempt WHERE draft_id=?)",
                        draft);
                jdbc.update("DELETE FROM checkout_payment_attempt WHERE draft_id=?", draft);
                jdbc.update("DELETE FROM checkout_draft_line WHERE draft_id=?", draft);
                jdbc.update("DELETE FROM checkout_draft WHERE draft_id=?", draft);
            }
            for (String order : orders) {
                jdbc.update(
                        "DELETE FROM shipment_event WHERE line_id IN (SELECT line_id FROM order_line WHERE order_id=?)",
                        order);
                jdbc.update(
                        "DELETE FROM shipment WHERE line_id IN (SELECT line_id FROM order_line WHERE order_id=?)",
                        order);
                jdbc.update(
                        "DELETE FROM line_refund WHERE line_id IN (SELECT line_id FROM order_line WHERE order_id=?)",
                        order);
                jdbc.update("DELETE FROM order_fulfillment WHERE order_id=?", order);
                jdbc.update("DELETE FROM order_line WHERE order_id=?", order);
                jdbc.update("DELETE FROM payment_ledger WHERE order_id=?", order);
                jdbc.update("DELETE FROM orders WHERE order_id=?", order);
            }
            jdbc.update("DELETE FROM catalog_sku WHERE product_id=?", product);
            jdbc.update("DELETE FROM catalog_product WHERE product_id=?", product);
        }
        fixtureProducts.clear();
    }

    @Test
    void twoCommerceProcessesUseRealLocksAndRetainFaultEvidence() throws Exception {
        directory = Path.of(System.getProperty("resolveflow.d4.output", "target/d4-dual-" + UUID.randomUUID()))
                .toAbsolutePath();
        Files.createDirectory(directory);
        redis = new GenericContainer<>("redis:7.4-alpine").withExposedPorts(6379);
        redis.start();
        try {
            for (boolean locking : List.of(false, true)) {
                condition = locking ? "C" : "B";
                start("a", locking);
                start("b", locking);
                Fixture fixture = fixture("cold-" + condition);
                String id = "cold-" + condition;
                gate(id, fixture.product(), "hold");
                try (var pool = Executors.newFixedThreadPool(12)) {
                    var owner = pool.submit(() -> request("a", fixture.product()));
                    entered("a", id);
                    var same = pool.submit(() -> request("b", fixture.product()));
                    if (!locking) entered("b", id);
                    else {
                        assertThat(same.get(2, TimeUnit.SECONDS).get("status")).isEqualTo(503);
                    }
                    ungate("a", id);
                    if (!locking) ungate("b", id);
                    assertThat(owner.get(5, TimeUnit.SECONDS).get("status")).isEqualTo(200);
                    if (!locking)
                        assertThat(same.get(5, TimeUnit.SECONDS).get("status")).isEqualTo(200);
                    Files.delete(directory.resolve("gate.json"));
                    assertThat(request("b", fixture.product()).get("status")).isEqualTo(200);
                    var result = new LinkedHashMap<String, Object>();
                    result.put("scenario", "cold-smoke");
                    result.put("condition", condition);
                    result.put("fixture", fixture);
                    result.put("metrics_a", metrics("a"));
                    result.put("metrics_b", metrics("b"));
                    save(condition + "-cold", result);
                    outcomes.add(result);
                }
                failureRecovery(locking);
                killedOwner(locking);
                expiredOwner(locking);
                changedEpoch(locking);
                redisTimeout(locking);
                stop("a");
                stop("b");
            }
            save(
                    "summary",
                    Map.of(
                            "status",
                            "PASSED",
                            "rows",
                            outcomes,
                            "model_requests",
                            0,
                            "boundary",
                            "development smoke, not formal R120"));
        } catch (Throwable failure) {
            save("failure", Map.of("error", failure.toString(), "completed", outcomes.size()));
            throw failure;
        } finally {
            for (String node : new ArrayList<>(children.keySet())) stop(node);
            redis.stop();
        }
    }

    @Test
    void realTtlDifferentKeysBurstAndRedisDisconnectRecover() throws Exception {
        directory = Path.of(System.getProperty("resolveflow.d4.extra", "target/d4-extra-" + UUID.randomUUID()))
                .toAbsolutePath();
        Files.createDirectory(directory);
        int port;
        try (var socket = new java.net.ServerSocket(0)) {
            port = socket.getLocalPort();
        }
        int fixedPort = port;
        redis = new GenericContainer<>("redis:7.4-alpine")
                .withExposedPorts(6379)
                .withCreateContainerCmdModifier(command -> command.getHostConfig()
                        .withPortBindings(new com.github.dockerjava.api.model.PortBinding(
                                com.github.dockerjava.api.model.Ports.Binding.bindIpAndPort("127.0.0.1", fixedPort),
                                new com.github.dockerjava.api.model.ExposedPort(6379))));
        redis.start();
        try {
            for (boolean locking : List.of(false, true)) {
                condition = locking ? "C" : "B";
                start("a", locking);
                start("b", locking);
                Fixture f = fixture("ttl-" + condition), other = fixture("other-" + condition);
                assertThat(request("a", f.product()).get("status")).isEqualTo(200);
                String key = "d4:" + directory.getFileName() + ":" + condition + ":" + f.product() + ":"
                        + reviews.publicEpoch(f.product());
                assertThat(Integer.parseInt(redis.execInContainer("redis-cli", "TTL", key)
                                .getStdout()
                                .trim()))
                        .isBetween(1, 30);
                long expiresFrom = System.nanoTime();
                Thread.sleep(31000);
                assertThat(redis.execInContainer("redis-cli", "EXISTS", key)
                                .getStdout()
                                .trim())
                        .isEqualTo("0");
                String id = "burst-" + condition;
                gate(id, f.product(), "hold");
                try (var pool = Executors.newFixedThreadPool(30)) {
                    var owner = pool.submit(() -> request("a", f.product()));
                    entered("a", id);
                    var independent = request("b", other.product());
                    assertThat(independent.get("status")).isEqualTo(200);
                    // Other product has completed while the first product remains blocked.
                    assertThat(owner.isDone()).isFalse();
                    var start = new CountDownLatch(1);
                    var jobs = new ArrayList<Future<Map<String, Object>>>();
                    for (int n = 0; n < 29; n++) {
                        String node = n % 2 == 0 ? "b" : "a";
                        jobs.add(pool.submit(() -> {
                            start.await();
                            return request(node, f.product());
                        }));
                    }
                    start.countDown();
                    if (!locking) entered("b", id);
                    else
                        assertThat(jobs.getFirst().get(2, TimeUnit.SECONDS).get("status"))
                                .isEqualTo(503);
                    ungate("a", id);
                    ungate("b", id);
                    var responses = new ArrayList<Map<String, Object>>();
                    responses.add(owner.get(5, TimeUnit.SECONDS));
                    for (var future : jobs) responses.add(future.get(5, TimeUnit.SECONDS));
                    assertThat(responses)
                            .allSatisfy(row -> assertThat(row.get("status")).isIn(200, 503));
                    Files.delete(directory.resolve("gate.json"));
                    for (int n = 0; n < 10; n++)
                        assertThat(request(n % 2 == 0 ? "a" : "b", f.product()).get("status"))
                                .isEqualTo(200);
                    record(
                            "R01-ttl-burst",
                            f,
                            Map.of(
                                    "ttl_wait_ms",
                                    (System.nanoTime() - expiresFrom) / 1000000.0,
                                    "responses",
                                    responses,
                                    "independent_product",
                                    other.product(),
                                    "independent_response",
                                    independent));
                }
                Fixture unplugged = fixture("disconnect-" + condition);
                redis.getDockerClient()
                        .stopContainerCmd(redis.getContainerId())
                        .withTimeout(1)
                        .exec();
                var disconnected = new ArrayList<Map<String, Object>>();
                for (int n = 0; n < 4; n++) {
                    var response = request(n % 2 == 0 ? "a" : "b", unplugged.product());
                    assertThat(response.get("status")).isEqualTo(200);
                    disconnected.add(response);
                }
                redis.getDockerClient()
                        .startContainerCmd(redis.getContainerId())
                        .exec();
                waitFor(
                        "same Redis port restored",
                        () -> {
                            try {
                                return redis.execInContainer("redis-cli", "PING")
                                        .getStdout()
                                        .trim()
                                        .equals("PONG");
                            } catch (Exception unavailable) {
                                return false;
                            }
                        },
                        5);
                String freshKey = "d4:" + directory.getFileName() + ":" + condition + ":" + unplugged.product() + ":"
                        + reviews.publicEpoch(unplugged.product());
                var restored = new ArrayList<Map<String, Object>>();
                long deadline = System.nanoTime() + TimeUnit.SECONDS.toNanos(5);
                while (System.nanoTime() < deadline) {
                    var response = request(restored.size() % 2 == 0 ? "a" : "b", unplugged.product());
                    assertThat(response.get("status")).isEqualTo(200);
                    restored.add(response);
                    if (redis.execInContainer("redis-cli", "EXISTS", freshKey)
                            .getStdout()
                            .trim()
                            .equals("1")) break;
                    Thread.sleep(50);
                }
                assertThat(redis.execInContainer("redis-cli", "EXISTS", freshKey)
                                .getStdout()
                                .trim())
                        .isEqualTo("1");
                assertThat(inflight(metrics("a"))).isZero();
                assertThat(inflight(metrics("b"))).isZero();
                record(
                        "R06-disconnect",
                        unplugged,
                        Map.of(
                                "disconnect_responses",
                                disconnected,
                                "restored_responses",
                                restored,
                                "same_port",
                                fixedPort));
                stop("a");
                stop("b");
            }
            save(
                    "summary",
                    Map.of(
                            "status",
                            "PASSED",
                            "rows",
                            outcomes,
                            "model_requests",
                            0,
                            "boundary",
                            "development TTL/burst/disconnect supplement, not formal R120"));
        } catch (Throwable failure) {
            save("failure", Map.of("error", failure.toString(), "completed", outcomes.size()));
            throw failure;
        } finally {
            for (String node : new ArrayList<>(children.keySet())) stop(node);
            redis.stop();
        }
    }
}
