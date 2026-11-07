package com.resolveflow.caseservice.shopping;

import static org.mockito.ArgumentMatchers.*;
import static org.mockito.Mockito.*;

import com.resolveflow.caseservice.CaseDatabaseTest;
import com.resolveflow.shared.shopping.CartWire.*;
import java.util.List;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.resttestclient.autoconfigure.AutoConfigureRestTestClient;
import org.springframework.boot.test.context.TestConfiguration;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Primary;
import org.springframework.http.MediaType;
import org.springframework.test.web.servlet.client.RestTestClient;
import tools.jackson.databind.ObjectMapper;

@AutoConfigureRestTestClient
class CartBuyerApiTest extends CaseDatabaseTest {
    @Autowired
    RestTestClient rest;

    @Autowired
    CommerceShoppingClient commerce;

    @TestConfiguration
    static class Configuration {
        @Bean
        @Primary
        CommerceShoppingClient shoppingStub() {
            return mock(CommerceShoppingClient.class);
        }
    }

    @BeforeEach
    void prepare() {
        reset(commerce);
        when(commerce.cart(anyString(), anyString()))
                .thenAnswer(inv -> new Group(inv.getArgument(0), "合成店铺", 0, "CNY", List.of()));
        when(commerce.cartWrite(anyString(), any())).thenAnswer(inv -> new Receipt(inv.getArgument(0), 1));
    }

    private String login(String user, String password) {
        String json = rest.post()
                .uri("/api/v1/auth/login")
                .contentType(MediaType.APPLICATION_JSON)
                .body(java.util.Map.of("username", user, "password", password))
                .exchange()
                .expectStatus()
                .isOk()
                .expectBody(String.class)
                .returnResult()
                .getResponseBody();
        return new ObjectMapper().readTree(json).get("access_token").asString();
    }

    private String body =
            "{\"sku_id\":\"SKU-2001-CREAM\",\"quantity\":1,\"expected_revision\":0,\"expected_sku_version\":1}";

    @Test
    void publicAndMerchantActorsCannotReadOrWriteCart() {
        rest.get().uri("/api/v1/shop/cart").exchange().expectStatus().isUnauthorized();
        rest.post()
                .uri("/api/v1/shop/cart/M-1001/items")
                .contentType(MediaType.APPLICATION_JSON)
                .body(body)
                .exchange()
                .expectStatus()
                .isUnauthorized();
        for (var pair : List.of(
                new String[] {"demo-admin", "demo-pass-1100"}, new String[] {"demo-reviewer", "demo-pass-1003"})) {
            var t = login(pair[0], pair[1]);
            rest.get()
                    .uri("/api/v1/shop/cart")
                    .header("Authorization", "Bearer " + t)
                    .exchange()
                    .expectStatus()
                    .isForbidden();
            rest.post()
                    .uri("/api/v1/shop/cart/M-1001/items")
                    .header("Authorization", "Bearer " + t)
                    .header("Idempotency-Key", "cart-test")
                    .contentType(MediaType.APPLICATION_JSON)
                    .body(body)
                    .exchange()
                    .expectStatus()
                    .isForbidden();
        }
        verifyNoInteractions(commerce);
    }

    @Test
    void trustedBindingsComposeReadAndIgnoreForgedQueryScope() {
        var t = login("demo-buyer", "demo-pass-4001");
        rest.get()
                .uri("/api/v1/shop/cart?buyer_id=other")
                .header("Authorization", "Bearer " + t)
                .exchange()
                .expectStatus()
                .isOk()
                .expectBody()
                .jsonPath("$.stores.length()")
                .isEqualTo(jdbc.queryForObject(
                        "SELECT COUNT(*) FROM identity_merchant WHERE enabled=TRUE", Integer.class));
        verify(commerce).cart("M-1001", "B-3001");
        verify(commerce).cart("M-1002", "B-3001");
        rest.post()
                .uri("/api/v1/shop/cart/M-1002/items?buyer_id=other")
                .header("Authorization", "Bearer " + t)
                .header("Idempotency-Key", "cart-test")
                .contentType(MediaType.APPLICATION_JSON)
                .body(body)
                .exchange()
                .expectStatus()
                .isOk()
                .expectBody()
                .jsonPath("$.buyer_id")
                .doesNotExist();
        verify(commerce)
                .cartWrite(
                        "M-1002",
                        new Command("M-1002", "B-3001", "cart-test", new Request("SKU-2001-CREAM", 1, 0L, 1L)));
    }

    @Test
    void unknownStoreMissingKeyAndPrivateBodyAreRejectedBeforeForwarding() {
        var t = login("demo-buyer", "demo-pass-4001");
        rest.post()
                .uri("/api/v1/shop/cart/M-evil/items")
                .header("Authorization", "Bearer " + t)
                .header("Idempotency-Key", "cart-test")
                .contentType(MediaType.APPLICATION_JSON)
                .body(body)
                .exchange()
                .expectStatus()
                .isNotFound();
        rest.post()
                .uri("/api/v1/shop/cart/M-1001/items")
                .header("Authorization", "Bearer " + t)
                .contentType(MediaType.APPLICATION_JSON)
                .body(body)
                .exchange()
                .expectStatus()
                .isBadRequest();
        rest.post()
                .uri("/api/v1/shop/cart/M-1001/items")
                .header("Authorization", "Bearer " + t)
                .header("Idempotency-Key", "cart-test")
                .contentType(MediaType.APPLICATION_JSON)
                .body(body.substring(0, body.length() - 1) + ",\"buyer_id\":\"other\"}")
                .exchange()
                .expectStatus()
                .isBadRequest();
        verifyNoInteractions(commerce);
    }

    @Test
    void storeOutageFailsWholeReadInsteadOfReturningPartialCart() {
        var t = login("demo-buyer", "demo-pass-4001");
        when(commerce.cart(eq("M-1002"), anyString()))
                .thenThrow(new com.resolveflow.caseservice.order.CommerceOrderLineClient.CommerceUnavailableException(
                        "offline", null));
        rest.get()
                .uri("/api/v1/shop/cart")
                .header("Authorization", "Bearer " + t)
                .exchange()
                .expectStatus()
                .isEqualTo(503);
    }

    @Test
    void quoteAndMultilineDraftUseTrustedBindingsAndOnlyBuyerRole() throws Exception {
        var json = new ObjectMapper();
        var fixtures = json.readTree(java.nio.file.Files.readString(
                java.nio.file.Path.of("../../contracts/core/fixtures/cart-checkout.json")));
        var request = json.treeToValue(
                fixtures.get("CartQuoteRequest"), com.resolveflow.shared.shopping.MultiCheckoutWire.QuoteRequest.class);
        var q = json.treeToValue(
                fixtures.get("CartQuote"), com.resolveflow.shared.shopping.MultiCheckoutWire.Quote.class);
        when(commerce.cartQuote(anyString(), any())).thenReturn(q);
        var t = login("demo-buyer", "demo-pass-4001");
        rest.post()
                .uri("/api/v1/shop/cart/M-1001/quote?buyer_id=foreign")
                .header("Authorization", "Bearer " + t)
                .contentType(MediaType.APPLICATION_JSON)
                .body(fixtures.get("CartQuoteRequest").toString())
                .exchange()
                .expectStatus()
                .isOk()
                .expectBody()
                .jsonPath("$.lines.length()")
                .isEqualTo(q.lines().size());
        verify(commerce)
                .cartQuote(
                        "M-1001",
                        new com.resolveflow.shared.shopping.MultiCheckoutWire.QuoteCommand(
                                "M-1001", "B-3001", request));
        for (var pair : List.<String[]>of(new String[] {"demo-admin", "demo-pass-1100"})) {
            var actor = login(pair[0], pair[1]);
            for (var suffix : List.of("quote", "drafts"))
                rest.post()
                        .uri("/api/v1/shop/cart/M-1001/" + suffix)
                        .header("Authorization", "Bearer " + actor)
                        .header("Idempotency-Key", "original")
                        .contentType(MediaType.APPLICATION_JSON)
                        .body(fixtures.get(suffix.equals("quote") ? "CartQuoteRequest" : "CartDraftRequest")
                                .toString())
                        .exchange()
                        .expectStatus()
                        .isForbidden();
        }
        var purchaseFixtures = json.readTree(java.nio.file.Files.readString(
                java.nio.file.Path.of("../../contracts/core/fixtures/checkout-payment.json")));
        when(commerce.cartDraft(anyString(), any()))
                .thenReturn(json.treeToValue(
                        purchaseFixtures.get("CheckoutPurchase"),
                        com.resolveflow.shared.shopping.CheckoutWire.Purchase.class));
        var body = fixtures.get("CartDraftRequest").toString();
        rest.post()
                .uri("/api/v1/shop/cart/M-1001/drafts")
                .header("Authorization", "Bearer " + t)
                .header("Idempotency-Key", "original")
                .contentType(MediaType.APPLICATION_JSON)
                .body(body)
                .exchange()
                .expectStatus()
                .isOk();
        verify(commerce)
                .cartDraft(
                        "M-1001",
                        new com.resolveflow.shared.shopping.MultiCheckoutWire.Command(
                                "M-1001",
                                "B-3001",
                                "original",
                                json.treeToValue(
                                        fixtures.get("CartDraftRequest"),
                                        com.resolveflow.shared.shopping.MultiCheckoutWire.Request.class)));
        rest.post()
                .uri("/api/v1/shop/cart/M-1001/drafts")
                .header("Authorization", "Bearer " + t)
                .contentType(MediaType.APPLICATION_JSON)
                .body(body)
                .exchange()
                .expectStatus()
                .isBadRequest();
        rest.post()
                .uri("/api/v1/shop/cart/M-evil/drafts")
                .header("Authorization", "Bearer " + t)
                .header("Idempotency-Key", "original")
                .contentType(MediaType.APPLICATION_JSON)
                .body(body)
                .exchange()
                .expectStatus()
                .isNotFound();
        rest.post()
                .uri("/api/v1/shop/cart/M-1001/drafts")
                .header("Authorization", "Bearer " + t)
                .header("Idempotency-Key", "original")
                .contentType(MediaType.APPLICATION_JSON)
                .body(body.substring(0, body.length() - 1) + ",\"total_amount\":1}")
                .exchange()
                .expectStatus()
                .isBadRequest();
        verify(commerce, times(1)).cartDraft(anyString(), any());
    }
}
