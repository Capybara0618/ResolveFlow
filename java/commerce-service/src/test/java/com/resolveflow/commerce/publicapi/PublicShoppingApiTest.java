package com.resolveflow.commerce.publicapi;

import static org.assertj.core.api.Assertions.*;

import com.resolveflow.commerce.CommerceDatabaseTest;
import com.resolveflow.shared.error.ApiError;
import com.resolveflow.shared.security.*;
import com.resolveflow.shared.security.IdentityAccessWire.*;
import com.resolveflow.shared.shopping.ShippingWire;
import com.sun.net.httpserver.HttpServer;
import java.net.InetSocketAddress;
import java.time.*;
import java.util.*;
import java.util.concurrent.atomic.*;
import org.junit.jupiter.api.*;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.resttestclient.autoconfigure.AutoConfigureRestTestClient;
import org.springframework.http.MediaType;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.test.context.*;
import org.springframework.test.web.servlet.client.RestTestClient;
import tools.jackson.databind.*;

/** Real Commerce transactions with an HTTP account authority stub, never a trading proxy. */
@AutoConfigureRestTestClient
class PublicShoppingApiTest extends CommerceDatabaseTest {
    static final ObjectMapper JSON = new ObjectMapper();
    static final JwtCodec TOKENS = new JwtCodec("resolveflow-core-demo-identity-secret", Duration.ofHours(1));
    static final AtomicBoolean disabled = new AtomicBoolean(), addressGone = new AtomicBoolean();
    static final AtomicInteger addressReads = new AtomicInteger();
    static final HttpServer identity = identity();
    static final String ADDRESS = "00000000-0000-0000-0000-000000000001";

    @Autowired
    RestTestClient rest;

    @Autowired
    JdbcTemplate db;

    String buyer;

    @DynamicPropertySource
    static void identityAddress(DynamicPropertyRegistry r) {
        r.add(
                "resolveflow.identity.base-url",
                () -> "http://127.0.0.1:" + identity.getAddress().getPort());
    }

    @AfterAll
    static void stop() {
        identity.stop(0);
    }

    @BeforeEach
    void setup() {
        buyer = "PUBLIC-" + UUID.randomUUID();
        disabled.set(false);
        addressGone.set(false);
        addressReads.set(0);
    }

    static HttpServer identity() {
        try {
            var server = HttpServer.create(new InetSocketAddress("127.0.0.1", 0), 0);
            server.createContext("/internal/v1/identity/resolve", e -> {
                var service = TOKENS.verifyAsService(
                        e.getRequestHeaders().getFirst("Authorization").substring(7), Instant.now());
                assertThat(service.subject()).isEqualTo("commerce-service");
                assertThat(service.hasScope(ServiceScopes.IDENTITY_RESOLVE)).isTrue();
                var request = JSON.readValue(e.getRequestBody(), Resolve.class);
                var p = TOKENS.principalFromAuthorizationHeader(request.user_authorization(), Instant.now());
                int status = disabled.get() ? 401 : 200;
                ShippingWire.Snapshot shipping = null;
                if (request.shipping() != null) {
                    addressReads.incrementAndGet();
                    if (addressGone.get()) status = 404;
                    else
                        shipping = new ShippingWire.Snapshot(
                                ADDRESS, 1, "原收件人", "13800000000", "浙江省", "杭州市", "西湖区", "测试路1号");
                }
                Object body = status == 200
                        ? new Context(
                                p.subject(),
                                p.merchantId(),
                                p.role(),
                                p.customerId(),
                                p.buyerId(),
                                1,
                                p.isPlatformBuyer()
                                        ? List.of(
                                                new Binding("M-1001", p.buyerId(), "店一"),
                                                new Binding("M-1002", p.buyerId(), "店二"))
                                        : List.of(),
                                shipping)
                        : ApiError.of(
                                status == 401 ? "UNAUTHENTICATED" : "NOT_FOUND",
                                "synthetic authority refusal",
                                false,
                                "test");
                byte[] bytes = JSON.writeValueAsBytes(body);
                e.getResponseHeaders().set("Content-Type", "application/json");
                e.sendResponseHeaders(status, bytes.length);
                try (var out = e.getResponseBody()) {
                    out.write(bytes);
                }
            });
            server.start();
            return server;
        } catch (Exception e) {
            throw new IllegalStateException(e);
        }
    }

    String token(String owner) {
        return "Bearer "
                + TOKENS.issue(new AuthenticatedPrincipal(owner, null, Role.CUSTOMER, null, owner), 1, Instant.now());
    }

    String shipping() {
        return "\"shipping\":{\"address_id\":\"" + ADDRESS + "\",\"expected_version\":1}";
    }

    String draft(String sku) {
        return "{\"sku_id\":\"" + sku + "\",\"quantity\":1,\"expected_sku_version\":1," + shipping() + "}";
    }

    RestTestClient.ResponseSpec post(String path, String owner, String key, String body) {
        return rest.post()
                .uri(path)
                .header("Authorization", token(owner))
                .header("Idempotency-Key", key)
                .contentType(MediaType.APPLICATION_JSON)
                .body(body)
                .exchange();
    }

    JsonNode created(String sku, String key) {
        return JSON.readTree(post("/api/v1/shop/drafts", buyer, key, draft(sku))
                .expectStatus()
                .isOk()
                .expectBody()
                .returnResult()
                .getResponseBody());
    }

    @Test
    void authenticationAndCompositeCartOwnershipAreEnforcedInsideCommerce() {
        rest.get()
                .uri("/api/v1/shop/cart")
                .header("X-User", buyer)
                .exchange()
                .expectStatus()
                .isUnauthorized();
        String body =
                "{\"sku_id\":\"SKU-1001-BLACK\",\"quantity\":1,\"expected_revision\":0,\"expected_sku_version\":1}";
        post("/api/v1/shop/cart/M-1001/items", buyer, UUID.randomUUID().toString(), body)
                .expectStatus()
                .isOk();
        rest.get()
                .uri("/api/v1/shop/cart")
                .header("Authorization", token(buyer))
                .exchange()
                .expectStatus()
                .isOk()
                .expectBody()
                .jsonPath("$.stores[0].items[0].sku_id")
                .isEqualTo("SKU-1001-BLACK");
        rest.get()
                .uri("/api/v1/shop/cart")
                .header("Authorization", token("other-" + buyer))
                .exchange()
                .expectStatus()
                .isOk()
                .expectBody()
                .jsonPath("$.stores[0].items.length()")
                .isEqualTo(0);
        post("/api/v1/shop/cart/M-1002/items", buyer, UUID.randomUUID().toString(), body)
                .expectStatus()
                .isNotFound();
        post(
                        "/api/v1/shop/cart/M-1001/items",
                        buyer,
                        UUID.randomUUID().toString(),
                        body.replace("}", ",\"customer_id\":\"other\"}"))
                .expectStatus()
                .isBadRequest();
        disabled.set(true);
        rest.get()
                .uri("/api/v1/shop/cart")
                .header("Authorization", token(buyer))
                .exchange()
                .expectStatus()
                .isUnauthorized();
    }

    @Test
    void crossStoreDraftReplaySurvivesDeletedAddressAndRejectsOtherBuyers() {
        String key = UUID.randomUUID().toString();
        var first = created("SKU-2001-CREAM", key);
        String id = first.path("draft_id").asString();
        int reads = addressReads.get();
        addressGone.set(true);
        post("/api/v1/shop/drafts", buyer, key, draft("SKU-2001-CREAM"))
                .expectStatus()
                .isOk()
                .expectBody()
                .jsonPath("$.draft_id")
                .isEqualTo(id);
        assertThat(addressReads.get()).isEqualTo(reads);
        rest.get()
                .uri("/api/v1/shop/drafts/" + id)
                .header("Authorization", token("other-" + buyer))
                .exchange()
                .expectStatus()
                .isNotFound();
        post("/api/v1/shop/drafts", buyer, key, draft("SKU-2001-CREAM").replace("\"quantity\":1", "\"quantity\":2"))
                .expectStatus()
                .isEqualTo(409);
    }

    @Test
    void paymentReplayPublishesOneOrderAndPreservesShippingSnapshot() {
        String id = created("SKU-1001-BLACK", UUID.randomUUID().toString())
                .path("draft_id")
                .asString();
        String key = UUID.randomUUID().toString();
        post("/api/v1/shop/drafts/" + id + "/payment", buyer, key, "{}")
                .expectStatus()
                .isOk();
        post("/api/v1/shop/drafts/" + id + "/payment", buyer, key, "{}")
                .expectStatus()
                .isOk();
        assertThat(db.queryForObject("SELECT COUNT(*) FROM orders WHERE customer_id=?", Integer.class, buyer))
                .isEqualTo(1);
        rest.get()
                .uri("/api/v1/shop/purchases/draft:" + id + "/shipping")
                .header("Authorization", token(buyer))
                .exchange()
                .expectStatus()
                .isOk()
                .expectBody()
                .jsonPath("$.shipping.recipient")
                .isEqualTo("原收件人");
        post("/api/v1/shop/drafts/" + id + "/payment", "other-" + buyer, key, "{}")
                .expectStatus()
                .isNotFound();
        rest.get()
                .uri("/api/v1/shop/purchases?limit=1")
                .header("Authorization", token(buyer))
                .exchange()
                .expectStatus()
                .isOk()
                .expectBody()
                .jsonPath("$.items.length()")
                .isEqualTo(1);
    }

    @Test
    void cartCheckoutUsesCurrentRevisionAndServerPrices() {
        post(
                        "/api/v1/shop/cart/M-1001/items",
                        buyer,
                        UUID.randomUUID().toString(),
                        "{\"sku_id\":\"SKU-1001-BLACK\",\"quantity\":1,\"expected_revision\":0,\"expected_sku_version\":1}")
                .expectStatus()
                .isOk();
        String body =
                "{\"expected_revision\":1,\"lines\":[{\"sku_id\":\"SKU-1001-BLACK\",\"quantity\":1,\"expected_sku_version\":1}],"
                        + shipping() + "}";
        String key = UUID.randomUUID().toString();
        post("/api/v1/shop/cart/M-1001/drafts", buyer, key, body)
                .expectStatus()
                .isOk()
                .expectBody()
                .jsonPath("$.total_amount")
                .isEqualTo(32900);
        post("/api/v1/shop/cart/M-1001/drafts", buyer, key, body).expectStatus().isOk();
        assertThat(db.queryForObject("SELECT COUNT(*) FROM checkout_draft WHERE customer_id=?", Integer.class, buyer))
                .isEqualTo(1);
    }

    @Test
    void crossStorePurchasePaginationCannotBeReusedByOtherBuyerOrFilter() {
        created("SKU-1001-BLACK", UUID.randomUUID().toString());
        created("SKU-2001-CREAM", UUID.randomUUID().toString());
        var first = JSON.readTree(rest.get()
                .uri("/api/v1/shop/purchases?limit=1")
                .header("Authorization", token(buyer))
                .exchange()
                .expectStatus()
                .isOk()
                .expectBody()
                .returnResult()
                .getResponseBody());
        String cursor = first.path("next_cursor").asString();
        assertThat(cursor).isNotBlank();
        var next = JSON.readTree(rest.get()
                .uri("/api/v1/shop/purchases?limit=1&cursor=" + cursor)
                .header("Authorization", token(buyer))
                .exchange()
                .expectStatus()
                .isOk()
                .expectBody()
                .returnResult()
                .getResponseBody());
        assertThat(next.path("items").get(0).path("purchase_id").asString())
                .isNotEqualTo(first.path("items").get(0).path("purchase_id").asString());
        rest.get()
                .uri("/api/v1/shop/purchases?limit=1&cursor=" + cursor)
                .header("Authorization", token("other-" + buyer))
                .exchange()
                .expectStatus()
                .isBadRequest();
        rest.get()
                .uri("/api/v1/shop/purchases?limit=1&store_id=M-1001&cursor=" + cursor)
                .header("Authorization", token(buyer))
                .exchange()
                .expectStatus()
                .isBadRequest();
    }

    String merchantToken(String store) {
        return "Bearer "
                + TOKENS.issue(
                        new AuthenticatedPrincipal("merchant-" + store, store, Role.MERCHANT_ADMIN, null),
                        1,
                        Instant.now());
    }

    JsonNode paid() {
        String id = created("SKU-1001-BLACK", UUID.randomUUID().toString())
                .path("draft_id")
                .asString();
        return JSON.readTree(post(
                        "/api/v1/shop/drafts/" + id + "/payment",
                        buyer,
                        UUID.randomUUID().toString(),
                        "{}")
                .expectStatus()
                .isOk()
                .expectBody()
                .returnResult()
                .getResponseBody());
    }

    @Test
    void merchantTradesAndFulfillmentKeepTenantRoleAndReplayBoundaries() {
        var payment = paid();
        String order = payment.path("order_id").asString();
        rest.get()
                .uri("/api/v1/merchant/orders/" + order)
                .header("Authorization", merchantToken("M-1001"))
                .exchange()
                .expectStatus()
                .isOk();
        rest.get()
                .uri("/api/v1/merchant/orders/" + order)
                .header("Authorization", merchantToken("M-1002"))
                .exchange()
                .expectStatus()
                .isNotFound();
        rest.get()
                .uri("/api/v1/merchant/orders/" + order)
                .header("Authorization", token(buyer))
                .exchange()
                .expectStatus()
                .isForbidden();
        String key = UUID.randomUUID().toString();
        for (int i = 0; i < 2; i++)
            rest.post()
                    .uri("/api/v1/merchant/orders/" + order + "/simulated-shipment")
                    .header("Authorization", merchantToken("M-1001"))
                    .header("Idempotency-Key", key)
                    .contentType(MediaType.APPLICATION_JSON)
                    .body("{\"expected_version\":1}")
                    .exchange()
                    .expectStatus()
                    .isOk();
        rest.get()
                .uri("/api/v1/shop/purchases/draft:" + payment.path("draft_id").asString() + "/fulfillment")
                .header("Authorization", token(buyer))
                .exchange()
                .expectStatus()
                .isOk()
                .expectBody()
                .jsonPath("$.synthetic")
                .isEqualTo(true);
    }

    @Test
    void ownReviewAndMerchantReplyUseLocalEligibilityAndOwnership() {
        var payment = paid();
        String line = payment.path("line_id").asString();
        String path = "/api/v1/shop/orders/lines/" + line + "/review";
        post(path, buyer, UUID.randomUUID().toString(), "{\"rating\":5,\"body\":\"已购合成评价\",\"expected_version\":0}")
                .expectStatus()
                .isEqualTo(409);
        db.update(
                "UPDATE shipment SET status='DELIVERED',carrier_conclusion='DELIVERED',source_version=2 WHERE line_id=?",
                line);
        post(
                        path,
                        "other-" + buyer,
                        UUID.randomUUID().toString(),
                        "{\"rating\":5,\"body\":\"其他买家\",\"expected_version\":0}")
                .expectStatus()
                .isNotFound();
        var review = JSON.readTree(post(
                        path,
                        buyer,
                        UUID.randomUUID().toString(),
                        "{\"rating\":5,\"body\":\"已购合成评价\",\"expected_version\":0}")
                .expectStatus()
                .isOk()
                .expectBody()
                .returnResult()
                .getResponseBody());
        String reply = "/api/v1/merchant/reviews/" + review.path("review_id").asLong() + "/reply";
        rest.post()
                .uri(reply)
                .header("Authorization", merchantToken("M-1002"))
                .contentType(MediaType.APPLICATION_JSON)
                .body("{\"body\":\"跨店回复\",\"expected_version\":1}")
                .exchange()
                .expectStatus()
                .isNotFound();
        rest.post()
                .uri(reply)
                .header("Authorization", merchantToken("M-1001"))
                .contentType(MediaType.APPLICATION_JSON)
                .body("{\"body\":\"本店合成回复\",\"expected_version\":1}")
                .exchange()
                .expectStatus()
                .isOk();
        rest.get()
                .uri(path)
                .header("Authorization", token("other-" + buyer))
                .exchange()
                .expectStatus()
                .isNotFound();
    }

    @Test
    void merchantCatalogCannotReadOrChangeOtherStoreProducts() {
        rest.get()
                .uri("/api/v1/merchant/products/P-1001")
                .header("Authorization", merchantToken("M-1001"))
                .exchange()
                .expectStatus()
                .isOk();
        rest.get()
                .uri("/api/v1/merchant/products/P-1001")
                .header("Authorization", merchantToken("M-1002"))
                .exchange()
                .expectStatus()
                .isNotFound();
        rest.get()
                .uri("/api/v1/merchant/products")
                .header("Authorization", token(buyer))
                .exchange()
                .expectStatus()
                .isForbidden();
        rest.post()
                .uri("/api/v1/merchant/products/P-1001")
                .header("Authorization", merchantToken("M-1001"))
                .contentType(MediaType.APPLICATION_JSON)
                .body("{\"merchant_id\":\"M-1002\"}")
                .exchange()
                .expectStatus()
                .isBadRequest();
    }
}
