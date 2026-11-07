package com.resolveflow.caseservice.shopping;

import static org.assertj.core.api.Assertions.*;
import static org.mockito.Mockito.*;

import com.resolveflow.caseservice.auth.BuyerScopes;
import com.resolveflow.shared.security.*;
import com.sun.net.httpserver.HttpServer;
import java.net.*;
import java.nio.charset.StandardCharsets;
import java.nio.file.*;
import java.time.*;
import java.util.*;
import org.junit.jupiter.api.Test;
import org.springframework.web.client.RestClient;
import tools.jackson.databind.ObjectMapper;

class BuyerPurchaseHttpFanoutTest {
    @Test
    void actualLoopbackRequestsStayOnePerBoundStoreOrOneSelectedStore() throws Exception {
        var codec = new JwtCodec("synthetic-purchase-fanout-only", Duration.ofMinutes(10));
        var observed = Collections.synchronizedList(new ArrayList<String>());
        var server = HttpServer.create(new InetSocketAddress("127.0.0.1", 0), 0);
        server.createContext("/internal/v1/shop/purchases", exchange -> {
            String token = exchange.getRequestHeaders().getFirst("Authorization");
            codec.verifyAsService(token.substring("Bearer ".length()), Instant.now());
            observed.add(exchange.getRequestURI().getRawQuery());
            byte[] body = "{\"items\":[],\"next_cursor\":null}".getBytes(StandardCharsets.UTF_8);
            exchange.getResponseHeaders().set("Content-Type", "application/json");
            exchange.sendResponseHeaders(200, body.length);
            try (var output = exchange.getResponseBody()) {
                output.write(body);
            }
        });
        server.start();
        try {
            var client = new CommerceShoppingClient(
                    RestClient.builder(),
                    codec,
                    "http://127.0.0.1:" + server.getAddress().getPort());
            var buyer = new AuthenticatedPrincipal("D3-buyer", null, Role.CUSTOMER, "D3-platform");
            var scopes = mock(BuyerScopes.class);
            var service = new BuyerPurchaseService(scopes, client);
            var measurements = new ArrayList<Map<String, Object>>();
            for (int stores = 1; stores <= 3; stores++) {
                var bindings = new ArrayList<BuyerScopes.Scope>();
                for (int i = 1; i <= stores; i++) bindings.add(new BuyerScopes.Scope("M-" + i, "C-" + i, "store-" + i));
                when(scopes.list(buyer)).thenReturn(bindings);
                for (int size : List.of(1, 24, 48))
                    for (int repeat = 0; repeat < 10; repeat++) {
                        observed.clear();
                        assertThat(service.list(buyer, null, null, null, size).items())
                                .isEmpty();
                        assertThat(observed).hasSize(stores);
                        for (int i = 1; i <= stores; i++) {
                            int index = i;
                            assertThat(observed)
                                    .anySatisfy(query -> assertThat(query)
                                            .contains(
                                                    "merchant_id=M-" + index, "buyer_id=C-" + index, "limit=" + size));
                        }
                        measurements.add(Map.of(
                                "stores",
                                stores,
                                "size",
                                size,
                                "repeat",
                                repeat,
                                "selected_store",
                                false,
                                "requests",
                                List.copyOf(observed)));
                        observed.clear();
                        assertThat(service.list(buyer, "M-1", null, null, size).items())
                                .isEmpty();
                        assertThat(observed).hasSize(1);
                        assertThat(observed.getFirst()).contains("merchant_id=M-1", "buyer_id=C-1");
                        measurements.add(Map.of(
                                "stores",
                                stores,
                                "size",
                                size,
                                "repeat",
                                repeat,
                                "selected_store",
                                true,
                                "requests",
                                List.copyOf(observed)));
                    }
            }
            String output = System.getProperty("resolveflow.purchase.fanout");
            if (output != null) {
                Path file = Path.of(output);
                Files.createDirectories(file.getParent());
                Files.writeString(
                        file,
                        new ObjectMapper().writeValueAsString(measurements),
                        StandardCharsets.UTF_8,
                        StandardOpenOption.CREATE_NEW);
            }
        } finally {
            server.stop(0);
        }
    }
}
