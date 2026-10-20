package com.resolveflow.commerce.shipment;

import static org.assertj.core.api.Assertions.*;

import com.resolveflow.commerce.CommerceDatabaseTest;
import com.resolveflow.commerce.catalog.CheckoutPayments;
import com.resolveflow.commerce.catalog.MerchantTradeService;
import com.resolveflow.commerce.catalog.ShoppingService;
import com.resolveflow.shared.security.JwtCodec;
import com.resolveflow.shared.shopping.CheckoutWire.PayCommand;
import com.resolveflow.shared.shopping.FulfillmentWire.ShipCommand;
import com.resolveflow.shared.shopping.ShoppingWire.DraftCommand;
import com.resolveflow.shared.shopping.ShoppingWire.DraftRequest;
import java.sql.Timestamp;
import java.time.Instant;
import java.util.UUID;
import java.util.concurrent.CompletableFuture;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.resttestclient.autoconfigure.AutoConfigureRestTestClient;
import org.springframework.test.web.servlet.client.RestTestClient;

@AutoConfigureRestTestClient
@org.springframework.boot.test.context.SpringBootTest(
        webEnvironment = org.springframework.boot.test.context.SpringBootTest.WebEnvironment.RANDOM_PORT)
class LogisticsSimulatorTest extends CommerceDatabaseTest {
    @Autowired
    ShoppingService shop;

    @Autowired
    CheckoutPayments payments;

    @Autowired
    MerchantTradeService trades;

    @Autowired
    org.springframework.jdbc.core.JdbcTemplate jdbc;

    @Autowired
    ShipmentReadService shipments;

    @Autowired
    RestTestClient rest;

    @Autowired
    JwtCodec codec;

    @Autowired
    com.resolveflow.commerce.catalog.CartService cart;

    @Autowired
    com.resolveflow.commerce.catalog.MultiCheckoutService multi;

    private String paid(boolean ship) {
        String customer = "SIM-" + UUID.randomUUID();
        var draft = shop.create(new DraftCommand(
                "M-1001", customer, UUID.randomUUID().toString(), new DraftRequest("SKU-1001-BLACK", 1, 1L)));
        var order = payments.pay(
                        draft.draftId(),
                        new PayCommand("M-1001", customer, UUID.randomUUID().toString()))
                .orderId();
        if (ship)
            trades.ship(
                    order,
                    new ShipCommand("M-1001", "sim-test", UUID.randomUUID().toString(), 1L));
        return order;
    }

    private String line(String order) {
        return jdbc.queryForObject("SELECT line_id FROM order_line WHERE order_id=? LIMIT 1", String.class, order);
    }

    private void advance(String order, String merchant, long version, String scenario, String key, Instant at) {
        jdbc.execute((org.springframework.jdbc.core.ConnectionCallback<Void>) c -> {
            try (var s = c.prepareCall("CALL simulate_logistics(?,?,?,?,?,?)")) {
                s.setString(1, order);
                s.setString(2, merchant);
                s.setLong(3, version);
                s.setString(4, scenario);
                s.setString(5, key);
                s.setTimestamp(6, at == null ? null : Timestamp.from(at));
                s.execute();
            }
            return null;
        });
    }

    private void advance(String order, long version, String scenario, String key) {
        advance(order, "M-1001", version, scenario, key, null);
    }

    @Test
    void deliveredAdvancesSnapshotAndFulfillmentAndPreservesMoneyAndOldEvents() {
        String order = paid(true), line = line(order);
        var oldEvents = shipments.readShipment(line).orElseThrow().events();
        var money = jdbc.queryForMap("SELECT * FROM payment_ledger WHERE order_id=?", order);
        var slot = jdbc.queryForMap("SELECT * FROM line_refund WHERE line_id=?", line);
        advance(order, 2, "DELIVERED", "delivered");
        var snapshot = shipments.readShipment(line).orElseThrow();
        assertThat(snapshot.carrierConclusion()).isEqualTo("DELIVERED");
        assertThat(snapshot.sourceVersion()).isEqualTo(3);
        assertThat(snapshot.events()).startsWith(oldEvents.toArray(ShipmentRepository.ShipmentEventRow[]::new));
        assertThat(snapshot.events().getLast().code()).isEqualTo("DELIVERED");
        assertThat(trades.read(order, "M-1001").fulfillment().status()).isEqualTo("DELIVERED");
        assertThat(jdbc.queryForMap("SELECT * FROM payment_ledger WHERE order_id=?", order))
                .isEqualTo(money);
        assertThat(jdbc.queryForMap("SELECT * FROM line_refund WHERE line_id=?", line))
                .isEqualTo(slot);
        assertThatThrownBy(() -> advance(order, 3, "LOST", "terminal-backwards"))
                .hasMessageContaining("terminal");
    }

    @Test
    void delayedIsNotLostAndUnknownCanResumeBeforeLostTerminal() {
        String order = paid(true), line = line(order);
        advance(order, 2, "DELAYED", "delay");
        assertThat(shipments.readShipment(line).orElseThrow().carrierConclusion())
                .isEqualTo("IN_TRANSIT");
        assertThat(shipments.readShipment(line).orElseThrow().events().getLast().code())
                .isEqualTo("EXCEPTION_DELAYED");
        advance(order, 3, "UNKNOWN", "unknown");
        advance(order, 4, "IN_TRANSIT", "resume");
        advance(order, 5, "LOST", "lost");
        assertThat(shipments.readShipment(line).orElseThrow().carrierConclusion())
                .isEqualTo("LOST");
        assertThatThrownBy(() -> advance(order, 6, "DELIVERED", "lost-to-signed"))
                .hasMessageContaining("terminal");
    }

    @Test
    void retryReturnsOriginalReceiptAndChangedPayloadOrStaleVersionIsRejected() {
        String order = paid(true), line = line(order);
        advance(order, 2, "IN_TRANSIT", "same-key");
        advance(order, 2, "IN_TRANSIT", "same-key");
        assertThat(shipments.readShipment(line).orElseThrow().events()).hasSize(3);
        assertThatThrownBy(() -> advance(order, 2, "DELAYED", "same-key")).hasMessageContaining("different payload");
        assertThatThrownBy(() -> advance(order, 2, "LOST", "old-version")).hasMessageContaining("version");
        assertThat(shipments.readShipment(line).orElseThrow().sourceVersion()).isEqualTo(3);
    }

    @Test
    void wrongMerchantUnshippedAndBackdatedEventsDoNotMutateRecords() {
        String order = paid(true), line = line(order);
        var before = shipments.readShipment(line).orElseThrow();
        assertThatThrownBy(() -> advance(order, "M-1002", 2, "LOST", "wrong-store", null))
                .hasMessageContaining("ownership");
        assertThatThrownBy(() -> advance(order, "M-1001", 2, "LOST", "old-time", Instant.parse("2026-01-01T00:00:00Z")))
                .hasMessageContaining("time");
        assertThat(shipments.readShipment(line).orElseThrow()).isEqualTo(before);
        String unshipped = paid(false);
        assertThatThrownBy(() -> advance(unshipped, 1, "LOST", "not-shipped")).hasMessageContaining("shipped");
    }

    @Test
    void faultIsRealHttp503AndRecoveryDoesNotChangeLogistics() {
        String order = paid(true), line = line(order);
        var before = shipments.readShipment(line).orElseThrow();
        advance(order, 2, "UNAVAILABLE", "fault-on");
        String token = codec.issueServiceToken("case-service", null, null, "commerce:read", Instant.now());
        rest.get()
                .uri("/internal/v1/order-lines/" + line + "/shipment")
                .header("Authorization", "Bearer " + token)
                .exchange()
                .expectStatus()
                .isEqualTo(503);
        advance(order, 2, "AVAILABLE", "fault-off");
        rest.get()
                .uri("/internal/v1/order-lines/" + line + "/shipment")
                .header("Authorization", "Bearer " + token)
                .exchange()
                .expectStatus()
                .isOk();
        assertThat(shipments.readShipment(line).orElseThrow()).isEqualTo(before);
        assertThat(trades.read(order, "M-1001").fulfillment().version()).isEqualTo(2);
    }

    @Test
    void concurrentSameRequestAddsOnlyOneEvent() {
        String order = paid(true), line = line(order);
        var first = CompletableFuture.runAsync(() -> advance(order, 2, "IN_TRANSIT", "concurrent"));
        var second = CompletableFuture.runAsync(() -> advance(order, 2, "IN_TRANSIT", "concurrent"));
        CompletableFuture.allOf(first, second).join();
        assertThat(shipments.readShipment(line).orElseThrow().events()).hasSize(3);
    }

    private String multiPaid() {
        String buyer = "SIM-MULTI-" + UUID.randomUUID();
        for (var sku : java.util.List.of("SKU-1001-BLACK", "SKU-1002-WHITE")) {
            long revision = cart.read("M-1001", buyer).revision();
            cart.write(new com.resolveflow.shared.shopping.CartWire.Command(
                    "M-1001",
                    buyer,
                    UUID.randomUUID().toString(),
                    new com.resolveflow.shared.shopping.CartWire.Request(sku, 1, revision, 1L)));
        }
        var q = multi.quote(new com.resolveflow.shared.shopping.MultiCheckoutWire.QuoteCommand(
                "M-1001",
                buyer,
                new com.resolveflow.shared.shopping.MultiCheckoutWire.QuoteRequest(
                        2L, java.util.List.of("SKU-1001-BLACK", "SKU-1002-WHITE"))));
        var draft = multi.create(new com.resolveflow.shared.shopping.MultiCheckoutWire.Command(
                "M-1001",
                buyer,
                UUID.randomUUID().toString(),
                new com.resolveflow.shared.shopping.MultiCheckoutWire.Request(
                        2L,
                        q.lines().stream()
                                .map(l -> new DraftRequest(l.skuId(), l.quantity(), l.skuVersion()))
                                .toList())));
        String order = payments.pay(
                        draft.draftId(),
                        new PayCommand("M-1001", buyer, UUID.randomUUID().toString()))
                .orderId();
        trades.ship(
                order, new ShipCommand("M-1001", "sim-test", UUID.randomUUID().toString(), 1L));
        return order;
    }

    @Test
    void multiLineOrderMovesTogetherAndIncompleteHistoryRollsBackWithoutReceipt() {
        String order = multiPaid();
        var lines = trades.read(order, "M-1001").fulfillment().lines();
        assertThat(lines).hasSize(2);
        String damaged = lines.getLast().lineId();
        jdbc.update("UPDATE shipment SET source_version=3 WHERE line_id=?", damaged);
        var goodBefore = shipments.readShipment(lines.getFirst().lineId()).orElseThrow();
        assertThatThrownBy(() -> advance(order, 2, "LOST", "rollback")).hasMessageContaining("history");
        assertThat(shipments.readShipment(lines.getFirst().lineId()).orElseThrow())
                .isEqualTo(goodBefore);
        assertThat(trades.read(order, "M-1001").fulfillment().version()).isEqualTo(2);
        assertThat(jdbc.queryForObject(
                        "SELECT COUNT(*) FROM shipment_simulation_request WHERE order_id=?", Integer.class, order))
                .isZero();
        jdbc.update("UPDATE shipment SET source_version=2 WHERE line_id=?", damaged);
        advance(order, 2, "LOST", "rollback");
        for (var item : trades.read(order, "M-1001").fulfillment().lines()) {
            assertThat(item.carrierConclusion()).isEqualTo("LOST");
            assertThat(item.sourceVersion()).isEqualTo(3);
            assertThat(item.events()).hasSize(3);
        }
        assertThat(jdbc.queryForObject(
                        "SELECT JSON_EXTRACT(receipt,'$.affected_lines') FROM shipment_simulation_request WHERE order_id=?",
                        Integer.class,
                        order))
                .isEqualTo(2);
    }

    @Test
    void eventLimitAndExplicitFutureTimeRejectWithoutPartialWrite() {
        String order = paid(true), line = line(order);
        var before = shipments.readShipment(line).orElseThrow();
        assertThatThrownBy(() -> advance(
                        order,
                        "M-1001",
                        2,
                        "IN_TRANSIT",
                        "future",
                        Instant.now().plusSeconds(86400)))
                .hasMessageContaining("future");
        assertThat(shipments.readShipment(line).orElseThrow()).isEqualTo(before);
        for (int i = 3; i <= 200; i++) {
            jdbc.update(
                    "INSERT INTO shipment_event(line_id,code,occurred_at,source_version) SELECT line_id,'IN_TRANSIT',occurred_at,? FROM shipment_event WHERE line_id=? AND source_version=2",
                    i,
                    line);
        }
        jdbc.update("UPDATE shipment SET source_version=200 WHERE line_id=?", line);
        assertThatThrownBy(() -> advance(order, 2, "DELIVERED", "overflow")).hasMessageContaining("limit");
        assertThat(shipments.readShipment(line).orElseThrow().events()).hasSize(200);
        assertThat(shipments.readShipment(line).orElseThrow().sourceVersion()).isEqualTo(200);
        assertThat(trades.read(order, "M-1001").fulfillment().version()).isEqualTo(2);
    }

    @Test
    void replayAfterFurtherProgressReturnsOriginalReceiptWithoutRevertingCurrentState() {
        String order = paid(true);
        advance(order, 2, "IN_TRANSIT", "first");
        advance(order, 3, "DELIVERED", "second");
        advance(order, 2, "IN_TRANSIT", "first");
        assertThat(trades.read(order, "M-1001").fulfillment().status()).isEqualTo("DELIVERED");
        assertThat(jdbc.queryForObject(
                        "SELECT JSON_EXTRACT(receipt,'$.fulfillment_version') FROM shipment_simulation_request WHERE order_id=? AND request_key='first'",
                        Long.class,
                        order))
                .isEqualTo(3);
        assertThat(jdbc.queryForObject(
                        "SELECT COUNT(*) FROM shipment_simulation_request WHERE order_id=?", Integer.class, order))
                .isEqualTo(2);
    }

    @Test
    void localPythonCliExecutesRealMysqlAndInspectDoesNotAdvanceServiceClock() throws Exception {
        String order = paid(true);
        var root = java.nio.file.Path.of("").toAbsolutePath();
        while (!java.nio.file.Files.isDirectory(root.resolve("scripts"))) root = root.getParent();
        String url;
        try (var connection = jdbc.getDataSource().getConnection()) {
            url = connection.getMetaData().getURL();
        }
        int port = java.net.URI.create(url.substring(5)).getPort();
        var containers = org.testcontainers.DockerClientFactory.instance().client().listContainersCmd().exec().stream()
                .filter(c -> java.util.Arrays.stream(c.getPorts())
                        .anyMatch(p -> java.util.Objects.equals(p.getPublicPort(), port)))
                .toList();
        assertThat(containers).hasSize(1);
        String container = containers.getFirst().getId();
        assertThat(container).matches("[0-9a-f]{12,64}");
        String code = "import sys;sys.path.insert(0,sys.argv.pop(1));from logistics_simulator import LocalMysql,main;"
                + "LocalMysql.__init__=lambda self:setattr(self,'container','" + container
                + "');raise SystemExit(main())";
        // Only the test binds its Testcontainers DB; production LocalMysql still checks demo labels.
        var python = root.resolve("agent/.venv/Scripts/python.exe");
        if (!java.nio.file.Files.exists(python)) python = root.resolve("agent/.venv/bin/python");
        var command = java.util.List.of(
                python.toString(),
                "-c",
                code,
                root.resolve("scripts").toString(),
                "advance",
                "--order-id",
                order,
                "--merchant-id",
                "M-1001",
                "--expected-version",
                "2",
                "--scenario",
                "DELAYED",
                "--request-key",
                "cli");
        var run = new ProcessBuilder(command).redirectErrorStream(true).start();
        String output = new String(run.getInputStream().readAllBytes(), java.nio.charset.StandardCharsets.UTF_8);
        assertThat(run.waitFor()).withFailMessage(output).isZero();
        assertThat(output).contains("EXCEPTION_DELAYED", "hours_since_last_event", "\"fulfillment_version\": 3");
        var again = new ProcessBuilder(command).redirectErrorStream(true).start();
        String replay = new String(again.getInputStream().readAllBytes(), java.nio.charset.StandardCharsets.UTF_8);
        assertThat(again.waitFor()).withFailMessage(replay).isZero();
        assertThat(shipments.readShipment(line(order)).orElseThrow().events()).hasSize(3);
        var before = shipments.readShipment(line(order)).orElseThrow();
        var observation = new ProcessBuilder(
                        python.toString(),
                        "-c",
                        code,
                        root.resolve("scripts").toString(),
                        "inspect",
                        "--order-id",
                        order,
                        "--merchant-id",
                        "M-1001",
                        "--observed-at",
                        Instant.now().plusSeconds(172800).toString())
                .redirectErrorStream(true)
                .start();
        String observed =
                new String(observation.getInputStream().readAllBytes(), java.nio.charset.StandardCharsets.UTF_8);
        assertThat(observation.waitFor()).withFailMessage(observed).isZero();
        assertThat(observed).contains("\"observation_time_is_service_clock\": false");
        assertThat(shipments.readShipment(line(order)).orElseThrow()).isEqualTo(before);
    }
}
