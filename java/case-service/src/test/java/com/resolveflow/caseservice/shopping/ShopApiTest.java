package com.resolveflow.caseservice.shopping;

import static org.mockito.ArgumentMatchers.*;
import static org.mockito.Mockito.*;

import com.resolveflow.caseservice.CaseDatabaseTest;
import com.resolveflow.shared.shopping.ShoppingWire.*;
import java.time.Instant;
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
class ShopApiTest extends CaseDatabaseTest {
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

    private final Draft draft = new Draft(
            "00000000-0000-4000-8000-000000004001",
            "M-1002",
            "拾光家居",
            "P-2001",
            "桌面台灯",
            "lamp",
            "SKU-2001-CREAM",
            "米白色",
            2,
            12900,
            25800,
            "CNY",
            "WAITING_PAYMENT",
            Instant.parse("2026-10-03T04:00:00Z"),
            Instant.parse("2026-10-03T04:15:00Z"));

    private String login(String user, String pass) {
        String body = rest.post()
                .uri("/api/v1/auth/login")
                .contentType(MediaType.APPLICATION_JSON)
                .body(java.util.Map.of("username", user, "password", pass))
                .exchange()
                .expectStatus()
                .isOk()
                .expectBody(String.class)
                .returnResult()
                .getResponseBody();
        return new ObjectMapper().readTree(body).get("access_token").asString();
    }

    @BeforeEach
    void prepare() {
        reset(commerce);
        when(commerce.stores()).thenReturn(List.of(new Store("M-1002", "拾光家居", "家居用品")));
        when(commerce.create(any())).thenAnswer(inv -> {
            DraftCommand c = inv.getArgument(0);
            if (!c.merchantId().equals("M-1002")) throw new CommerceShoppingClient.Refused(404, "NOT_FOUND", "missing");
            org.assertj.core.api.Assertions.assertThat(c.buyerId()).isEqualTo("B-3001");
            if (c.shippingSnapshot() == null)
                throw new CommerceShoppingClient.Refused(404, "SHIPPING_NOT_CAPTURED", "missing");
            org.assertj.core.api.Assertions.assertThat(c.shippingSnapshot().recipient())
                    .isEqualTo("测试收货人");
            return draft;
        });
        when(commerce.read(anyString(), anyString(), anyString()))
                .thenThrow(new CommerceShoppingClient.Refused(404, "NOT_FOUND", "missing"));
    }

    @Test
    void catalogIsPublicButCheckoutRequiresCurrentBuyer() {
        rest.get()
                .uri("/api/v1/shop/stores")
                .exchange()
                .expectStatus()
                .isOk()
                .expectBody()
                .jsonPath("$[0].name")
                .isEqualTo("拾光家居");
        rest.post()
                .uri("/api/v1/shop/drafts")
                .contentType(MediaType.APPLICATION_JSON)
                .body("{}")
                .exchange()
                .expectStatus()
                .isUnauthorized();
        for (var credentials : List.<String[]>of(new String[] {"demo-admin", "demo-pass-1100"}))
            rest.post()
                    .uri("/api/v1/shop/drafts")
                    .header("Authorization", "Bearer " + login(credentials[0], credentials[1]))
                    .contentType(MediaType.APPLICATION_JSON)
                    .body("{}")
                    .exchange()
                    .expectStatus()
                    .isForbidden();
        verify(commerce, never()).create(any());
    }

    @Test
    void checkoutScopeComesOnlyFromPersistedCompositeBinding() {
        String token = login("demo-buyer", "demo-pass-4001");
        String addressText = rest.post()
                .uri("/api/v1/account/addresses")
                .header("Authorization", "Bearer " + token)
                .contentType(MediaType.APPLICATION_JSON)
                .body(java.util.Map.of(
                        "recipient",
                        "测试收货人",
                        "phone",
                        "13000000000",
                        "province",
                        "测试省",
                        "city",
                        "测试市",
                        "district",
                        "测试区",
                        "detail",
                        "测试路1号",
                        "is_default",
                        true))
                .exchange()
                .expectStatus()
                .isOk()
                .expectBody(String.class)
                .returnResult()
                .getResponseBody();
        var address = new ObjectMapper().readTree(addressText);
        var choice = new com.resolveflow.shared.shopping.ShippingWire.Selection(
                address.get("address_id").asString(), address.get("version").asLong());

        rest.post()
                .uri("/api/v1/shop/drafts?merchant_id=M-evil&buyer_id=C-evil")
                .header("Authorization", "Bearer " + token)
                .header("Idempotency-Key", "test-key")
                .contentType(MediaType.APPLICATION_JSON)
                .body(new DraftRequest("SKU-2001-CREAM", 2, 1L, choice))
                .exchange()
                .expectStatus()
                .isOk()
                .expectBody()
                .jsonPath("$.total_amount")
                .isEqualTo(25800)
                .jsonPath("$.buyer_id")
                .doesNotExist()
                .jsonPath("$.idempotency_key")
                .doesNotExist();
        verify(commerce)
                .create(new DraftCommand(
                        "M-1002", "B-3001", "test-key", new DraftRequest("SKU-2001-CREAM", 2, 1L, choice)));
    }

    @Test
    void privateFieldsAndMissingKeyAreRejected() {
        String token = login("demo-buyer", "demo-pass-4001");
        rest.post()
                .uri("/api/v1/shop/drafts")
                .header("Authorization", "Bearer " + token)
                .header("Idempotency-Key", "test-key")
                .contentType(MediaType.APPLICATION_JSON)
                .body("{\"sku_id\":\"SKU-2001-CREAM\",\"quantity\":2,\"expected_sku_version\":1,\"total_amount\":1}")
                .exchange()
                .expectStatus()
                .isBadRequest();
        rest.post()
                .uri("/api/v1/shop/drafts")
                .header("Authorization", "Bearer " + token)
                .contentType(MediaType.APPLICATION_JSON)
                .body("{}")
                .exchange()
                .expectStatus()
                .isBadRequest();
        verify(commerce, never()).create(any());
    }

    @Test
    void nonexistentAndOtherOwnersDraftsAreIndistinguishable() {
        String token = login("demo-buyer", "demo-pass-4001");
        rest.get()
                .uri("/api/v1/shop/drafts/foreign")
                .header("Authorization", "Bearer " + token)
                .exchange()
                .expectStatus()
                .isNotFound();
        verify(commerce).read("foreign", "M-1001", "B-3001");
        verify(commerce).read("foreign", "M-1002", "B-3001");
    }
}
