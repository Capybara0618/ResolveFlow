package com.resolveflow.caseservice.shopping;

import static org.mockito.ArgumentMatchers.*;
import static org.mockito.Mockito.*;

import com.resolveflow.caseservice.CaseDatabaseTest;
import com.resolveflow.shared.shopping.FulfillmentWire.*;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.Map;
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
class MerchantTradeApiTest extends CaseDatabaseTest {
    @Autowired
    RestTestClient rest;

    @Autowired
    CommerceShoppingClient commerce;

    final ObjectMapper json = new ObjectMapper();
    Trade trade;

    @TestConfiguration
    static class FacadeStub {
        @Bean
        @Primary
        CommerceShoppingClient merchantShoppingStub() {
            return mock(CommerceShoppingClient.class);
        }
    }

    @BeforeEach
    void prepare() throws Exception {
        reset(commerce);
        var fixture = json.readTree(Files.readString(Path.of("../../contracts/core/fixtures/fulfillment.json")));
        trade = json.treeToValue(fixture.get("MerchantTrade"), Trade.class);
        when(commerce.merchantOrders(anyString(), any(), any(), any()))
                .thenReturn(new Trades(java.util.List.of(trade), null));
        when(commerce.merchantOrder(anyString(), eq("M-1001"))).thenReturn(trade);
        when(commerce.merchantOrder(anyString(), eq("M-1002")))
                .thenThrow(new CommerceShoppingClient.Refused(404, "NOT_FOUND", "订单不存在"));
        when(commerce.ship(anyString(), any())).thenReturn(trade.fulfillment());
        when(commerce.purchase(anyString(), eq("M-1001"), eq("C-B3001-M1001"))).thenReturn(trade.purchase());
        when(commerce.fulfillment(anyString(), eq("M-1001"), eq("C-B3001-M1001")))
                .thenReturn(trade.fulfillment());
    }

    private String auth(String user, String password) {
        String body = rest.post()
                .uri("/api/v1/auth/login")
                .contentType(MediaType.APPLICATION_JSON)
                .body(Map.of("username", user, "password", password))
                .exchange()
                .expectStatus()
                .isOk()
                .expectBody(String.class)
                .returnResult()
                .getResponseBody();
        return "Bearer " + json.readTree(body).get("access_token").asString();
    }

    @Test
    void anonymousCustomerBuyerAndReviewerCannotUseMerchantTransactions() {
        rest.get().uri("/api/v1/merchant/orders").exchange().expectStatus().isUnauthorized();
        for (var pair : new String[][] {
            {"demo-customer", "demo-pass-1001"}, {"demo-buyer", "demo-pass-4001"}, {"demo-reviewer", "demo-pass-1003"}
        }) {
            String token = auth(pair[0], pair[1]);
            rest.get()
                    .uri("/api/v1/merchant/orders")
                    .header("Authorization", token)
                    .exchange()
                    .expectStatus()
                    .isForbidden();
            rest.get()
                    .uri("/api/v1/merchant/orders/owned")
                    .header("Authorization", token)
                    .exchange()
                    .expectStatus()
                    .isForbidden();
            rest.post()
                    .uri("/api/v1/merchant/orders/owned/simulated-shipment")
                    .header("Authorization", token)
                    .header("Idempotency-Key", "original")
                    .contentType(MediaType.APPLICATION_JSON)
                    .body(Map.of("expected_version", 1))
                    .exchange()
                    .expectStatus()
                    .isForbidden();
        }
        verifyNoInteractions(commerce);
    }

    @Test
    void adminBindingIgnoresQueryAndDerivesActorButCannotReadOtherStore() {
        String token = auth("demo-admin", "demo-pass-1100");
        for (var invalid : java.util.List.of(
                "{\"expected_version\":1.5}",
                "{\"expected_version\":\"1\"}",
                "{\"expected_version\":9223372036854775808}"))
            rest.post()
                    .uri("/api/v1/merchant/orders/owned/simulated-shipment")
                    .header("Authorization", token)
                    .header("Idempotency-Key", "original")
                    .contentType(MediaType.APPLICATION_JSON)
                    .body(invalid)
                    .exchange()
                    .expectStatus()
                    .isBadRequest();
        rest.get()
                .uri("/api/v1/merchant/orders?merchant_id=M-1002&status=NOT_SHIPPED&limit=1")
                .header("Authorization", token)
                .exchange()
                .expectStatus()
                .isOk();
        verify(commerce).merchantOrders("M-1001", "NOT_SHIPPED", null, 1);
        rest.post()
                .uri("/api/v1/merchant/orders/owned/simulated-shipment")
                .header("Authorization", token)
                .header("Idempotency-Key", "original")
                .contentType(MediaType.APPLICATION_JSON)
                .body(Map.of("expected_version", 1))
                .exchange()
                .expectStatus()
                .isOk();
        verify(commerce).ship("owned", new ShipCommand("M-1001", "demo-admin", "original", 1L));
        rest.get()
                .uri("/api/v1/merchant/orders/owned")
                .header("Authorization", auth("demo-admin-m2", "demo-pass-2100"))
                .exchange()
                .expectStatus()
                .isNotFound();
    }

    @Test
    void missingKeyVersionAndForgedIdentityAreRejectedBeforeCommerce() {
        String token = auth("demo-admin", "demo-pass-1100");
        for (var body : java.util.List.of(
                "{}",
                "{\"expected_version\":0}",
                "{\"expected_version\":1,\"actor\":\"other\"}",
                "{\"expected_version\":1,\"merchant_id\":\"M-1002\"}",
                "{\"expected_version\":1,\"template\":\"DELIVERED\"}"))
            rest.post()
                    .uri("/api/v1/merchant/orders/owned/simulated-shipment")
                    .header("Authorization", token)
                    .header("Idempotency-Key", "original")
                    .contentType(MediaType.APPLICATION_JSON)
                    .body(body)
                    .exchange()
                    .expectStatus()
                    .isBadRequest();
        rest.post()
                .uri("/api/v1/merchant/orders/owned/simulated-shipment")
                .header("Authorization", token)
                .contentType(MediaType.APPLICATION_JSON)
                .body(Map.of("expected_version", 1))
                .exchange()
                .expectStatus()
                .isBadRequest();
        verifyNoInteractions(commerce);
    }

    @Test
    void buyerUsesOwnedPaidPurchaseAndOtherActorCannotReadFulfillment() {
        String path = "/api/v1/shop/purchases/draft%3Aowned/fulfillment";
        rest.get()
                .uri(path + "?customer_id=FOREIGN&merchant_id=M-1002")
                .header("Authorization", auth("demo-buyer", "demo-pass-4001"))
                .exchange()
                .expectStatus()
                .isOk();
        verify(commerce).fulfillment(trade.purchase().orderId(), "M-1001", "C-B3001-M1001");
        rest.get()
                .uri(path)
                .header("Authorization", auth("demo-customer", "demo-pass-1001"))
                .exchange()
                .expectStatus()
                .isForbidden();
        rest.get()
                .uri(path)
                .header("Authorization", auth("demo-admin", "demo-pass-1100"))
                .exchange()
                .expectStatus()
                .isForbidden();
    }

    @Test
    void commerceUnavailableIs503AndForeignPurchaseDoesNotLeak() {
        when(commerce.merchantOrders(anyString(), any(), any(), any()))
                .thenThrow(new com.resolveflow.caseservice.order.CommerceOrderLineClient.CommerceUnavailableException(
                        "synthetic outage", null));
        rest.get()
                .uri("/api/v1/merchant/orders")
                .header("Authorization", auth("demo-admin", "demo-pass-1100"))
                .exchange()
                .expectStatus()
                .isEqualTo(503);
        when(commerce.purchase(anyString(), anyString(), anyString()))
                .thenThrow(new CommerceShoppingClient.Refused(404, "NOT_FOUND", "订单不存在"));
        rest.get()
                .uri("/api/v1/shop/purchases/draft%3Aforeign/fulfillment")
                .header("Authorization", auth("demo-buyer", "demo-pass-4001"))
                .exchange()
                .expectStatus()
                .isNotFound();
        verify(commerce, never()).fulfillment(anyString(), anyString(), anyString());
    }
}
