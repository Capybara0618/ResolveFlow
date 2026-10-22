package com.resolveflow.caseservice.shopping;

import static org.mockito.ArgumentMatchers.*;
import static org.mockito.Mockito.*;

import com.resolveflow.caseservice.CaseDatabaseTest;
import com.resolveflow.shared.shopping.ProductReviewWire.*;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.List;
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
class ProductReviewApiTest extends CaseDatabaseTest {
    @Autowired
    RestTestClient rest;

    @Autowired
    CommerceShoppingClient commerce;

    private final ObjectMapper json = new ObjectMapper();
    private Review review;

    @TestConfiguration
    static class Stub {
        @Bean
        @Primary
        CommerceShoppingClient reviewCommerceStub() {
            return mock(CommerceShoppingClient.class);
        }
    }

    @BeforeEach
    void prepare() throws Exception {
        reset(commerce);
        review = json.treeToValue(
                json.readTree(Files.readString(Path.of("../../contracts/core/fixtures/product-reviews.json")))
                        .get("ProductReview"),
                Review.class);
        when(commerce.productReviews(anyString(), any(), any()))
                .thenReturn(new Page(List.of(review), new Summary(1, 5.0, List.of(1L, 0L, 0L, 0L, 0L)), null));
        when(commerce.ownReview(anyString(), anyString(), anyString()))
                .thenThrow(new CommerceShoppingClient.Refused(404, "NOT_FOUND", "missing"));
        doReturn(new Own(true, null, review)).when(commerce).ownReview("owned", "M-1001", "C-B3001-M1001");
        when(commerce.saveReview(eq("owned"), any())).thenReturn(review);
        when(commerce.merchantReviews(eq("M-1001"), any(), any())).thenReturn(new Page(List.of(review), null, null));
        when(commerce.replyReview(eq(1L), any())).thenAnswer(i -> {
            var c = (ReplyCommand) i.getArgument(1);
            if (!c.merchantId().equals("M-1001")) throw new CommerceShoppingClient.Refused(404, "NOT_FOUND", "missing");
            return review;
        });
    }

    private String auth(String user, String password) {
        var body = rest.post()
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
    void publicPageIsAnonymousButPrivateRoutesRequireBuyerOrMerchant() {
        rest.get()
                .uri("/api/v1/shop/products/P-1001/reviews")
                .exchange()
                .expectStatus()
                .isOk();
        rest.get()
                .uri("/api/v1/shop/orders/lines/owned/review")
                .exchange()
                .expectStatus()
                .isUnauthorized();
        var buyer = auth("demo-buyer", "demo-pass-4001");
        rest.get()
                .uri("/api/v1/merchant/reviews")
                .header("Authorization", buyer)
                .exchange()
                .expectStatus()
                .isForbidden();
        var legacy = auth("demo-customer", "demo-pass-1001");
        rest.get()
                .uri("/api/v1/shop/orders/lines/owned/review")
                .header("Authorization", legacy)
                .exchange()
                .expectStatus()
                .isForbidden();
    }

    @Test
    void trustedBuyerMappingAndStrictBodyNeverAcceptSelfReportedIdentity() {
        var buyer = auth("demo-buyer", "demo-pass-4001");
        rest.get()
                .uri("/api/v1/shop/orders/lines/owned/review?merchant_id=M-1002&customer_id=OTHER")
                .header("Authorization", buyer)
                .exchange()
                .expectStatus()
                .isOk();
        verify(commerce).ownReview("owned", "M-1001", "C-B3001-M1001");
        rest.get()
                .uri("/api/v1/shop/orders/lines/other/review")
                .header("Authorization", buyer)
                .exchange()
                .expectStatus()
                .isNotFound();
        rest.post()
                .uri("/api/v1/shop/orders/lines/owned/review")
                .header("Authorization", buyer)
                .contentType(MediaType.APPLICATION_JSON)
                .body(Map.of("rating", 5, "body", "text", "expected_version", 0, "customer_id", "OTHER"))
                .exchange()
                .expectStatus()
                .isBadRequest();
        rest.post()
                .uri("/api/v1/shop/orders/lines/owned/review")
                .header("Authorization", buyer)
                .contentType(MediaType.APPLICATION_JSON)
                .body(Map.of("rating", 5, "body", "text", "expected_version", 0))
                .exchange()
                .expectStatus()
                .isOk();
        verify(commerce).saveReview("owned", new Command("M-1001", "C-B3001-M1001", new Write(5L, "text", 0L)));
    }

    @Test
    void merchantScopeIsDerivedAndCrossStoreReplyIsNotFound() {
        var admin = auth("demo-admin", "demo-pass-1100");
        rest.get()
                .uri("/api/v1/merchant/reviews?merchant_id=M-1002")
                .header("Authorization", admin)
                .exchange()
                .expectStatus()
                .isOk();
        verify(commerce).merchantReviews("M-1001", null, null);
        var other = auth("demo-admin-m2", "demo-pass-2100");
        rest.post()
                .uri("/api/v1/merchant/reviews/1/reply")
                .header("Authorization", other)
                .contentType(MediaType.APPLICATION_JSON)
                .body(Map.of("body", "text", "expected_version", 1))
                .exchange()
                .expectStatus()
                .isNotFound();
    }
}
