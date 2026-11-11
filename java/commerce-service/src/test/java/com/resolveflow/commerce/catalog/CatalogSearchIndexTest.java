package com.resolveflow.commerce.catalog;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.when;

import com.resolveflow.shared.shopping.ShoppingWire.Product;
import com.sun.net.httpserver.HttpExchange;
import com.sun.net.httpserver.HttpServer;
import java.io.IOException;
import java.net.InetSocketAddress;
import java.nio.charset.StandardCharsets;
import java.util.List;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.web.client.RestClientResponseException;
import tools.jackson.databind.ObjectMapper;

class CatalogSearchIndexTest {
    private final ObjectMapper json = new ObjectMapper();
    private final ShoppingService shopping = mock(ShoppingService.class);
    private HttpServer server;
    private CatalogSearchIndex index;

    @BeforeEach
    void start() throws IOException {
        server = HttpServer.create(new InetSocketAddress("127.0.0.1", 0), 0);
        server.start();
        index = new CatalogSearchIndex(
                json, shopping, "http://127.0.0.1:" + server.getAddress().getPort(), "products");
    }

    @AfterEach
    void stop() {
        if (server != null) server.stop(0);
    }

    @Test
    void ignoresOnlyExternalVersionConflicts() {
        server.createContext("/products/_doc/P-1", exchange -> {
            var document = json.readTree(exchange.getRequestBody());
            boolean valid = "version=3&version_type=external"
                            .equals(exchange.getRequestURI().getQuery())
                    && document.path("id").asString().equals("P-1")
                    && document.path("version").asLong() == 3;
            respond(exchange, valid ? 409 : 400, """
                    {"error":{"type":"version_conflict_engine_exception"}}
                    """);
        });
        server.createContext("/products/_doc/P-2", exchange -> respond(exchange, 409, """
                {"error":{"type":"some_other_conflict"}}
                """));
        index.apply(new CatalogSearchIndex.Document("P-1", "M-1", "name", "desc", "home", false, 3));
        assertThatThrownBy(() ->
                        index.apply(new CatalogSearchIndex.Document("P-2", "M-1", "name", "desc", "home", false, 3)))
                .isInstanceOf(RestClientResponseException.class);
    }

    @Test
    void rechecksVisibilityAndUsesAnOpaqueCursorScopedToTheQuery() {
        server.createContext("/products/_search", exchange -> {
            var request = json.readTree(exchange.getRequestBody());
            respond(exchange, 200, request.has("search_after") ? """
                    {"hits":{"hits":[{"sort":[2.0,"P-3"]}]},"_shards":{"failed":0}}
                    """ : """
                    {"hits":{"hits":[{"sort":[4.0,"P-1"]},{"sort":[3.0,"P-2"]},{"sort":[2.0,"P-3"]}]},"_shards":{"failed":0}}
                    """);
        });
        when(shopping.searchProducts(List.of("P-1", "P-2", "P-3"), "home", null))
                .thenReturn(List.of(product("P-2"), product("P-3")));
        when(shopping.searchProducts(List.of("P-3"), "home", null)).thenReturn(List.of(product("P-3")));
        var first = index.search("lamp", "home", null, null, 1);
        assertThat(first.items()).extracting(Product::productId).containsExactly("P-2");
        var second = index.search("lamp", "home", null, first.nextAfter(), 1);
        assertThat(second.items()).extracting(Product::productId).containsExactly("P-3");
        assertThat(second.nextAfter()).isNull();
        assertThatThrownBy(() -> index.search("other", "home", null, first.nextAfter(), 1))
                .isInstanceOf(IllegalArgumentException.class);
    }

    private static Product product(String id) {
        return new Product(id, "M-1", "store", "name", "description", "home", "lamp", 500, "CNY", List.of(), null);
    }

    private static void respond(HttpExchange exchange, int status, String body) throws IOException {
        byte[] bytes = body.getBytes(StandardCharsets.UTF_8);
        exchange.getResponseHeaders().set("Content-Type", "application/json");
        exchange.sendResponseHeaders(status, bytes.length);
        try (var output = exchange.getResponseBody()) {
            output.write(bytes);
        }
    }
}
