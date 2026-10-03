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
                new String[] {"demo-customer", "demo-pass-1001"},
                new String[] {"demo-admin", "demo-pass-1100"},
                new String[] {"demo-reviewer", "demo-pass-1003"})) {
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
                .uri("/api/v1/shop/cart?customer_id=other")
                .header("Authorization", "Bearer " + t)
                .exchange()
                .expectStatus()
                .isOk()
                .expectBody()
                .jsonPath("$.stores.length()")
                .isEqualTo(2);
        verify(commerce).cart("M-1001", "C-B3001-M1001");
        verify(commerce).cart("M-1002", "C-B3001-M1002");
        rest.post()
                .uri("/api/v1/shop/cart/M-1002/items?customer_id=other")
                .header("Authorization", "Bearer " + t)
                .header("Idempotency-Key", "cart-test")
                .contentType(MediaType.APPLICATION_JSON)
                .body(body)
                .exchange()
                .expectStatus()
                .isOk()
                .expectBody()
                .jsonPath("$.customer_id")
                .doesNotExist();
        verify(commerce)
                .cartWrite(
                        "M-1002",
                        new Command("M-1002", "C-B3001-M1002", "cart-test", new Request("SKU-2001-CREAM", 1, 0L, 1L)));
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
                .body(body.substring(0, body.length() - 1) + ",\"customer_id\":\"other\"}")
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
}
