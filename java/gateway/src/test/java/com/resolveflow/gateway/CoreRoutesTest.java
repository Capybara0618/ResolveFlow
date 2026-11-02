package com.resolveflow.gateway;

import static org.assertj.core.api.Assertions.assertThat;

import com.sun.net.httpserver.HttpServer;
import java.io.IOException;
import java.net.InetSocketAddress;
import java.nio.charset.StandardCharsets;
import java.util.concurrent.atomic.AtomicReference;
import org.junit.jupiter.api.AfterAll;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.ValueSource;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.beans.factory.annotation.Qualifier;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.boot.webtestclient.autoconfigure.AutoConfigureWebTestClient;
import org.springframework.cloud.gateway.route.Route;
import org.springframework.cloud.gateway.route.RouteLocator;
import org.springframework.test.context.DynamicPropertyRegistry;
import org.springframework.test.context.DynamicPropertySource;
import org.springframework.test.web.reactive.server.WebTestClient;
import reactor.core.publisher.Flux;

@SpringBootTest(webEnvironment = SpringBootTest.WebEnvironment.RANDOM_PORT)
@AutoConfigureWebTestClient
class CoreRoutesTest {

    static final AtomicReference<String> forwarded = new AtomicReference<>();
    static final java.util.concurrent.CountDownLatch supportFirstReceived = new java.util.concurrent.CountDownLatch(1);
    static final java.util.concurrent.atomic.AtomicBoolean supportFlushed =
            new java.util.concurrent.atomic.AtomicBoolean();
    static final AtomicReference<String> supportForwarded = new AtomicReference<>();
    static final HttpServer upstream = startUpstream();
    static final AtomicReference<String> commerceForwarded = new AtomicReference<>();
    static final HttpServer commerce = startCommerce();

    @DynamicPropertySource
    static void caseAddress(DynamicPropertyRegistry properties) {
        properties.add(
                "resolveflow.case.base-url",
                () -> "http://127.0.0.1:" + upstream.getAddress().getPort());
        properties.add(
                "resolveflow.commerce.base-url",
                () -> "http://127.0.0.1:" + commerce.getAddress().getPort());
    }

    @AfterAll
    static void stopUpstream() {
        upstream.stop(0);
        commerce.stop(0);
    }

    private static HttpServer startCommerce() {
        try {
            var server = HttpServer.create(new InetSocketAddress("127.0.0.1", 0), 0);
            server.createContext("/api/v1/", exchange -> {
                commerceForwarded.set(exchange.getRequestMethod() + " " + exchange.getRequestURI() + " "
                        + exchange.getRequestHeaders().getFirst("X-Merchant"));
                byte[] body = "{\"owner\":\"commerce\"}".getBytes(StandardCharsets.UTF_8);
                exchange.getResponseHeaders().set("Content-Type", "application/json");
                exchange.sendResponseHeaders(200, body.length);
                try (var out = exchange.getResponseBody()) {
                    out.write(body);
                }
            });
            server.start();
            return server;
        } catch (IOException e) {
            throw new IllegalStateException(e);
        }
    }

    @ParameterizedTest
    @ValueSource(
            strings = {
                "/api/v1/shop/stores",
                "/api/v1/shop/stores/M-1001",
                "/api/v1/shop/products?query=headphones&limit=12",
                "/api/v1/shop/products/P-1001",
                "/api/v1/shop/products/P-1001/presentation",
                "/api/v1/shop/stores/M-1001/presentation",
                "/api/v1/shop/products/P-1001/reviews?before=20&limit=5"
            })
    void publicCatalogGoesDirectlyToCommerceWithOriginalPathAndQuery(String path) {
        webTestClient
                .get()
                .uri(path)
                .header("X-Merchant", "forged")
                .exchange()
                .expectStatus()
                .isOk()
                .expectBody()
                .jsonPath("$.owner")
                .isEqualTo("commerce");
        assertThat(commerceForwarded.get()).isEqualTo("GET " + path + " null");
    }

    @Test
    void quoteGoesToCommerceButPrivateAndMediaPathsAndWrongMethodsStayOnCase() {
        webTestClient
                .post()
                .uri("/api/v1/shop/quote")
                .bodyValue("{}")
                .exchange()
                .expectStatus()
                .isOk()
                .expectBody()
                .jsonPath("$.owner")
                .isEqualTo("commerce");
        for (String path : new String[] {
            "/api/v1/shop/drafts",
            "/api/v1/shop/cart",
            "/api/v1/shop/media/image-1",
            "/api/v1/shop/products/P-1001/private",
            "/api/v1/shop/orders/lines/line-1/review"
        }) {
            webTestClient.get().uri(path).exchange().expectStatus().isNotFound();
        }
        webTestClient
                .post()
                .uri("/api/v1/shop/products")
                .bodyValue("{}")
                .exchange()
                .expectStatus()
                .isNotFound();
        webTestClient
                .get()
                .uri("/internal/v1/shop/products")
                .exchange()
                .expectStatus()
                .isNotFound();
    }

    private static HttpServer startUpstream() {
        try {
            HttpServer server = HttpServer.create(new InetSocketAddress("127.0.0.1", 0), 0);
            server.createContext("/api/v1/cases/case-1/events", exchange -> {
                forwarded.set(exchange.getRequestMethod() + " " + exchange.getRequestURI() + " "
                        + exchange.getRequestHeaders().getFirst("Authorization") + " "
                        + exchange.getRequestHeaders().getFirst("Last-Event-ID") + " "
                        + exchange.getRequestHeaders().getFirst("X-User"));
                byte[] frame = "id: ev-2\nevent: CASE_UPDATED\ndata: {}\n\n".getBytes(StandardCharsets.UTF_8);
                exchange.getResponseHeaders().set("Content-Type", "text/event-stream");
                exchange.sendResponseHeaders(200, frame.length);
                try (var output = exchange.getResponseBody()) {
                    output.write(frame);
                }
            });
            server.createContext("/api/v1/support/conversations/c-1/events", exchange -> {
                supportForwarded.set(exchange.getRequestHeaders().getFirst("Authorization") + " "
                        + exchange.getRequestHeaders().getFirst("Last-Event-ID") + " "
                        + exchange.getRequestHeaders().getFirst("X-User"));
                exchange.getResponseHeaders().set("Content-Type", "text/event-stream");
                exchange.getResponseHeaders().set("Cache-Control", "no-store");
                exchange.getResponseHeaders().set("X-Accel-Buffering", "no");
                exchange.sendResponseHeaders(200, 0);
                try (var output = exchange.getResponseBody()) {
                    output.write(
                            "id: 1\nevent: turn.started\ndata: {\"phase\":1}\n\n".getBytes(StandardCharsets.UTF_8));
                    output.flush();
                    try {
                        supportFlushed.set(supportFirstReceived.await(2, java.util.concurrent.TimeUnit.SECONDS));
                    } catch (InterruptedException interrupted) {
                        Thread.currentThread().interrupt();
                    }
                    output.write(
                            "id: 2\nevent: answer.committed\ndata: {\"phase\":2}\n\n".getBytes(StandardCharsets.UTF_8));
                    output.flush();
                }
            });
            server.start();
            return server;
        } catch (IOException error) {
            throw new IllegalStateException(error);
        }
    }

    @Autowired
    @Qualifier("coreApiRoutes")
    RouteLocator locator;

    @Autowired
    WebTestClient webTestClient;

    @Test
    void routesPublicApiToCaseServiceWithoutChangingThePath() {
        Route route = Flux.from(locator.getRoutes())
                .filter(candidate -> candidate.getId().equals("case-core-api"))
                .blockFirst();
        assertThat(route).isNotNull();
        assertThat(route.getUri().toString())
                .isEqualTo("http://127.0.0.1:" + upstream.getAddress().getPort());
    }

    @Test
    void forwardsAuthenticatedEventStreamAndResumeHeaderButStripsSpoofedIdentity() {
        webTestClient
                .get()
                .uri("/api/v1/cases/case-1/events")
                .header("Authorization", "Bearer test-token")
                .header("Last-Event-ID", "ev-1")
                .header("X-User", "forged")
                .exchange()
                .expectStatus()
                .isOk()
                .expectHeader()
                .contentTypeCompatibleWith("text/event-stream")
                .expectBody(String.class)
                .value(body -> assertThat(body).contains("id: ev-2"));
        assertThat(forwarded.get()).isEqualTo("GET /api/v1/cases/case-1/events Bearer test-token ev-1 null");
    }

    @Test
    void consultationFirstFrameReachesClientBeforeUpstreamSendsTheTail() {
        var frames = webTestClient
                .get()
                .uri("/api/v1/support/conversations/c-1/events")
                .header("Authorization", "Bearer buyer-token")
                .header("Last-Event-ID", "0")
                .header("X-User", "forged")
                .exchange()
                .expectStatus()
                .isOk()
                .expectHeader()
                .valueEquals("Cache-Control", "no-store")
                .expectHeader()
                .valueEquals("X-Accel-Buffering", "no")
                .returnResult(String.class)
                .getResponseBody()
                .doOnNext(frame -> {
                    if (frame.contains("\"phase\":1")) supportFirstReceived.countDown();
                })
                .collectList()
                .block(java.time.Duration.ofSeconds(5));
        assertThat(frames).hasSize(2);
        assertThat(supportFlushed.get())
                .as("gateway must deliver first event before upstream completion")
                .isTrue();
        assertThat(supportForwarded.get()).isEqualTo("Bearer buyer-token 0 null");
    }
}
