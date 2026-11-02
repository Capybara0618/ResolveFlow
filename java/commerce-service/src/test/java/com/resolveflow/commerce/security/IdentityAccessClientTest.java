package com.resolveflow.commerce.security;

import static org.assertj.core.api.Assertions.*;

import com.resolveflow.shared.error.ApiError;
import com.resolveflow.shared.security.*;
import com.resolveflow.shared.security.IdentityAccessWire.*;
import com.sun.net.httpserver.HttpServer;
import java.net.InetSocketAddress;
import java.time.*;
import java.util.List;
import java.util.concurrent.atomic.*;
import org.junit.jupiter.api.*;
import org.springframework.web.client.RestClient;
import tools.jackson.databind.ObjectMapper;

class IdentityAccessClientTest {
    final ObjectMapper json = new ObjectMapper();
    final Instant now = Instant.now();
    final JwtCodec codec = new JwtCodec("boundary-synthetic-identity-secret", Duration.ofHours(1));
    final AuthenticatedPrincipal buyer = new AuthenticatedPrincipal("buyer", null, Role.CUSTOMER, null, "BUYER");
    final AtomicReference<String> response = new AtomicReference<>();
    final AtomicReference<String> forwarded = new AtomicReference<>();
    final AtomicInteger status = new AtomicInteger(200);
    final AtomicInteger calls = new AtomicInteger();
    HttpServer server;
    IdentityAccessClient client;

    @BeforeEach
    void start() throws Exception {
        server = HttpServer.create(new InetSocketAddress("127.0.0.1", 0), 0);
        server.createContext("/internal/v1/identity/resolve", exchange -> {
            calls.incrementAndGet();
            var identity = codec.verifyAsService(
                    exchange.getRequestHeaders().getFirst("Authorization").substring(7), now);
            assertThat(identity.subject()).isEqualTo("commerce-service");
            assertThat(identity.hasScope(ServiceScopes.IDENTITY_RESOLVE)).isTrue();
            forwarded.set(
                    new String(exchange.getRequestBody().readAllBytes(), java.nio.charset.StandardCharsets.UTF_8));
            byte[] body = response.get().getBytes(java.nio.charset.StandardCharsets.UTF_8);
            exchange.getResponseHeaders().set("Content-Type", "application/json");
            exchange.sendResponseHeaders(status.get(), body.length);
            try (var out = exchange.getResponseBody()) {
                out.write(body);
            }
        });
        server.start();
        client = new IdentityAccessClient(
                RestClient.builder(),
                codec,
                Clock.fixed(now, ZoneOffset.UTC),
                "http://127.0.0.1:" + server.getAddress().getPort());
        response.set(json.writeValueAsString(context(1, List.of(new Binding("M-1", "C-1", "store")))));
    }

    @AfterEach
    void stop() {
        server.stop(0);
    }

    String user() {
        return "Bearer " + codec.issue(buyer, 1, now);
    }

    Context context(long version, List<Binding> bindings) {
        return new Context(buyer.subject(), null, Role.CUSTOMER, null, buyer.buyerId(), version, bindings, null);
    }

    @Test
    void carriesUserTokenOnlyInBodyAndUsesSeparateScopedServiceIdentity() {
        var result = client.resolve(user());
        assertThat(result.principal()).isEqualTo(buyer);
        assertThat(result.bindings().getFirst().customerId()).isEqualTo("C-1");
        assertThat(json.readTree(forwarded.get()).path("user_authorization").asString())
                .isEqualTo(user());
        assertThat(json.readTree(forwarded.get()).has("merchant_id")).isFalse();
    }

    @Test
    void absentInvalidAndServiceTokensNeverReachIdentityAuthority() {
        for (String value :
                new String[] {null, "Bearer invalid", "Bearer " + codec.issueServiceToken("agent-service", now)}) {
            assertThatThrownBy(() -> client.resolve(value))
                    .isInstanceOfSatisfying(
                            IdentityAccessClient.Refused.class,
                            e -> assertThat(e.status).isEqualTo(401));
        }
        assertThat(calls.get()).isZero();
    }

    @Test
    void revokedSessionStaysUnauthorizedAndUnavailableAuthorityFailsClosed() {
        status.set(401);
        response.set(json.writeValueAsString(ApiError.of("UNAUTHENTICATED", "session changed", false, "test")));
        assertThatThrownBy(() -> client.resolve(user()))
                .isInstanceOfSatisfying(
                        IdentityAccessClient.Refused.class,
                        e -> assertThat(e.status).isEqualTo(401));
        status.set(500);
        assertThatThrownBy(() -> client.resolve(user()))
                .isInstanceOfSatisfying(
                        IdentityAccessClient.Refused.class,
                        e -> assertThat(e.status).isEqualTo(503));
        status.set(200);
        response.set("not-json");
        assertThatThrownBy(() -> client.resolve(user()))
                .isInstanceOfSatisfying(
                        IdentityAccessClient.Refused.class,
                        e -> assertThat(e.status).isEqualTo(503));
    }

    @Test
    void mismatchedVersionPrincipalAndDuplicateBindingsAreProtocolFailures() {
        for (Context value : List.of(
                context(2, List.of()),
                new Context("other", null, Role.CUSTOMER, null, "BUYER", 1, List.of(), null),
                context(1, List.of(new Binding("M-1", "C-1", "a"), new Binding("M-1", "C-2", "b"))))) {
            response.set(json.writeValueAsString(value));
            assertThatThrownBy(() -> client.resolve(user()))
                    .isInstanceOfSatisfying(
                            IdentityAccessClient.Refused.class,
                            e -> assertThat(e.status).isEqualTo(503));
        }
    }

    @Test
    void transportFailureDoesNotFallBackToOfflineJwtOrCachedScope() {
        client.resolve(user());
        server.stop(0);
        assertThatThrownBy(() -> client.resolve(user()))
                .isInstanceOfSatisfying(
                        IdentityAccessClient.Refused.class,
                        e -> assertThat(e.status).isEqualTo(503));
    }
}
