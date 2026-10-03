package com.resolveflow.caseservice.shopping;

import static org.assertj.core.api.Assertions.*;
import static org.mockito.ArgumentMatchers.*;
import static org.mockito.Mockito.*;

import com.resolveflow.caseservice.CaseDatabaseTest;
import com.resolveflow.shared.shopping.CheckoutWire.*;
import java.nio.file.Files;
import java.nio.file.Path;
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
class CheckoutBuyerApiTest extends CaseDatabaseTest {
    @Autowired
    RestTestClient rest;

    @Autowired
    CommerceShoppingClient commerce;

    private final ObjectMapper json = new ObjectMapper();
    private Purchase purchase;

    @TestConfiguration
    static class Configuration {
        @Bean
        @Primary
        CommerceShoppingClient checkoutStub() {
            return mock(CommerceShoppingClient.class);
        }
    }

    private String token(String user, String pass) {
        var response = rest.post()
                .uri("/api/v1/auth/login")
                .contentType(MediaType.APPLICATION_JSON)
                .body(java.util.Map.of("username", user, "password", pass))
                .exchange()
                .expectStatus()
                .isOk()
                .expectBody(String.class)
                .returnResult()
                .getResponseBody();
        return "Bearer " + json.readTree(response).get("access_token").asString();
    }

    @BeforeEach
    void prepare() throws Exception {
        reset(commerce);
        purchase = json.readValue(
                json.readTree(Files.readString(Path.of("../../contracts/core/fixtures/checkout-payment.json")))
                        .get("CheckoutPurchase")
                        .toString(),
                Purchase.class);
        when(commerce.pay(anyString(), any())).thenAnswer(inv -> {
            PayCommand c = inv.getArgument(1);
            if (!c.merchantId().equals("M-1001") || !c.customerId().equals("C-B3001-M1001"))
                throw new CommerceShoppingClient.Refused(404, "NOT_FOUND", "missing");
            return purchase.payment();
        });
        when(commerce.payment(anyString(), anyString(), anyString()))
                .thenThrow(new CommerceShoppingClient.Refused(404, "NOT_FOUND", "missing"));
        when(commerce.purchase(anyString(), anyString(), anyString()))
                .thenThrow(new CommerceShoppingClient.Refused(404, "NOT_FOUND", "missing"));
        when(commerce.purchases(anyString(), anyString(), nullable(String.class), nullable(String.class), anyInt()))
                .thenReturn(new Purchases(List.of(), null));
    }

    @Test
    void noSessionLegacyCustomerAndStaffCannotAccessPrivateTransactionsOrPay() {
        rest.get().uri("/api/v1/shop/purchases").exchange().expectStatus().isUnauthorized();
        for (var credentials : List.of(
                new String[] {"demo-customer", "demo-pass-1001"}, new String[] {"demo-admin", "demo-pass-1100"})) {
            var auth = token(credentials[0], credentials[1]);
            rest.get()
                    .uri("/api/v1/shop/purchases")
                    .header("Authorization", auth)
                    .exchange()
                    .expectStatus()
                    .isForbidden();
            rest.post()
                    .uri("/api/v1/shop/drafts/foreign/payment")
                    .header("Authorization", auth)
                    .header("Idempotency-Key", "key")
                    .contentType(MediaType.APPLICATION_JSON)
                    .body("{}")
                    .exchange()
                    .expectStatus()
                    .isForbidden();
        }
        verify(commerce, never()).pay(anyString(), any());
        verify(commerce, never()).purchases(anyString(), anyString(), any(), any(), anyInt());
    }

    @Test
    void paymentUsesPersistedScopeAndRejectsMoneyOrProviderInputs() {
        var auth = token("demo-buyer", "demo-pass-4001");
        rest.post()
                .uri("/api/v1/shop/drafts/owned/payment?merchant_id=M-evil&customer_id=C-evil")
                .header("Authorization", auth)
                .header("Idempotency-Key", "original")
                .contentType(MediaType.APPLICATION_JSON)
                .body("{}")
                .exchange()
                .expectStatus()
                .isOk()
                .expectBody()
                .jsonPath("$.total_amount")
                .isEqualTo(65800)
                .jsonPath("$.customer_id")
                .doesNotExist();
        verify(commerce).pay("owned", new PayCommand("M-1001", "C-B3001-M1001", "original"));
        for (String field : List.of("total_amount", "merchant_id", "customer_id", "status", "attempt_id"))
            rest.post()
                    .uri("/api/v1/shop/drafts/owned/payment")
                    .header("Authorization", auth)
                    .header("Idempotency-Key", "key")
                    .contentType(MediaType.APPLICATION_JSON)
                    .body("{\"" + field + "\":\"spoofed\"}")
                    .exchange()
                    .expectStatus()
                    .isBadRequest();
        rest.post()
                .uri("/api/v1/shop/drafts/owned/payment")
                .header("Authorization", auth)
                .contentType(MediaType.APPLICATION_JSON)
                .body("{}")
                .exchange()
                .expectStatus()
                .isBadRequest();
        verify(commerce, times(1)).pay(anyString(), any());
    }

    @Test
    void unknownAndForeignIdsAreIdentical404AndDoNotTakeClientScope() {
        var auth = token("demo-buyer", "demo-pass-4001");
        rest.get()
                .uri("/api/v1/shop/drafts/foreign/payment?customer_id=target")
                .header("Authorization", auth)
                .exchange()
                .expectStatus()
                .isNotFound();
        rest.get()
                .uri("/api/v1/shop/purchases/order:00000000-0000-4000-8000-000000009999")
                .header("Authorization", auth)
                .exchange()
                .expectStatus()
                .isNotFound();
        verify(commerce).payment("foreign", "M-1001", "C-B3001-M1001");
        verify(commerce).payment("foreign", "M-1002", "C-B3001-M1002");
    }

    @Test
    void listUsesEnabledBindingsAndStoreFilterNeverClaimsAnotherStore() {
        var auth = token("demo-buyer", "demo-pass-4001");
        rest.get()
                .uri("/api/v1/shop/purchases?store_id=M-1002&status=PAID&limit=3&customer_id=evil")
                .header("Authorization", auth)
                .exchange()
                .expectStatus()
                .isOk();
        verify(commerce).purchases("M-1002", "C-B3001-M1002", "PAID", null, 3);
        verify(commerce, never()).purchases(eq("M-1001"), anyString(), any(), any(), anyInt());
        rest.get()
                .uri("/api/v1/shop/purchases?limit=49")
                .header("Authorization", auth)
                .exchange()
                .expectStatus()
                .isBadRequest();
        rest.get()
                .uri("/api/v1/shop/purchases?status=FORGED")
                .header("Authorization", auth)
                .exchange()
                .expectStatus()
                .isBadRequest();
    }
}
