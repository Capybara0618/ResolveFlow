package com.resolveflow.caseservice.shopping;

import static org.assertj.core.api.Assertions.*;
import static org.springframework.test.web.client.match.MockRestRequestMatchers.*;
import static org.springframework.test.web.client.response.MockRestResponseCreators.*;

import com.resolveflow.caseservice.order.CommerceOrderLineClient.CommerceUnavailableException;
import com.resolveflow.shared.security.JwtCodec;
import com.resolveflow.shared.shopping.CheckoutWire.*;
import com.resolveflow.shared.shopping.ShoppingWire.*;
import java.nio.file.Files;
import java.nio.file.Path;
import java.time.Duration;
import java.time.Instant;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.http.HttpMethod;
import org.springframework.http.HttpStatus;
import org.springframework.http.MediaType;
import org.springframework.test.web.client.MockRestServiceServer;
import org.springframework.web.client.RestClient;
import tools.jackson.databind.ObjectMapper;

class CommerceShoppingClientTest {
    private final JwtCodec codec = new JwtCodec("resolveflow-core-demo-identity-secret", Duration.ofHours(1));
    private final ObjectMapper json = new ObjectMapper();
    private MockRestServiceServer server;
    private CommerceShoppingClient client;

    @BeforeEach
    void prepare() {
        var builder = RestClient.builder();
        server = MockRestServiceServer.bindTo(builder).build();
        client = new CommerceShoppingClient(builder, codec, "http://commerce.test");
    }

    private String fixture(String name) throws Exception {
        return json.readTree(Files.readString(Path.of("../../contracts/core/fixtures/shopping.json")))
                .get(name)
                .toString();
    }

    @Test
    void cartUsesOnlyCheckoutScopeAndRoundTripsPublicFacts() throws Exception {
        var all = json.readTree(Files.readString(Path.of("../../contracts/core/fixtures/cart.json")));
        server.expect(requestTo("http://commerce.test/internal/v1/shop/cart/M-1001?customer_id=trusted"))
                .andExpect(req -> assertThat(codec.verifyAsService(
                                        req.getHeaders()
                                                .getFirst("Authorization")
                                                .substring(7),
                                        Instant.now())
                                .scopes())
                        .containsExactly("commerce:checkout"))
                .andRespond(withSuccess(all.get("CartGroup").toString(), MediaType.APPLICATION_JSON));
        server.expect(requestTo("http://commerce.test/internal/v1/shop/cart/M-1001/items"))
                .andExpect(method(HttpMethod.POST))
                .andExpect(
                        content()
                                .json(
                                        "{\"merchant_id\":\"M-1001\",\"customer_id\":\"trusted\",\"idempotency_key\":\"original\",\"request\":{\"sku_id\":\"SKU-1001-BLACK\",\"quantity\":1,\"expected_revision\":0,\"expected_sku_version\":1}}"))
                .andRespond(withSuccess(all.get("CartReceipt").toString(), MediaType.APPLICATION_JSON));
        assertThat(json.readTree(json.writeValueAsString(client.cart("M-1001", "trusted"))))
                .isEqualTo(all.get("CartGroup"));
        assertThat(json.readTree(json.writeValueAsString(client.cartWrite(
                        "M-1001",
                        new com.resolveflow.shared.shopping.CartWire.Command(
                                "M-1001",
                                "trusted",
                                "original",
                                new com.resolveflow.shared.shopping.CartWire.Request("SKU-1001-BLACK", 1, 0L, 1L))))))
                .isEqualTo(all.get("CartReceipt"));
        server.verify();
    }

    @Test
    void multilineQuoteAndDraftUseCheckoutScopeAndSharedWire() throws Exception {
        var all = json.readTree(Files.readString(Path.of("../../contracts/core/fixtures/cart-checkout.json")));
        var purchase = json.readTree(Files.readString(Path.of("../../contracts/core/fixtures/checkout-payment.json")))
                .get("CheckoutPurchase");
        for (var suffix : new String[] {"quote", "drafts"})
            server.expect(requestTo("http://commerce.test/internal/v1/shop/cart/M-1001/" + suffix))
                    .andExpect(method(HttpMethod.POST))
                    .andExpect(req -> assertThat(codec.verifyAsService(
                                            req.getHeaders()
                                                    .getFirst("Authorization")
                                                    .substring(7),
                                            Instant.now())
                                    .scopes())
                            .containsExactly("commerce:checkout"))
                    .andRespond(withSuccess(
                            (suffix.equals("quote") ? all.get("CartQuote") : purchase).toString(),
                            MediaType.APPLICATION_JSON));
        var quote = json.treeToValue(
                all.get("CartQuoteCommand"), com.resolveflow.shared.shopping.MultiCheckoutWire.QuoteCommand.class);
        var draft = json.treeToValue(
                all.get("CartDraftCommand"), com.resolveflow.shared.shopping.MultiCheckoutWire.Command.class);
        assertThat(json.readTree(json.writeValueAsString(client.cartQuote("M-1001", quote))))
                .isEqualTo(all.get("CartQuote"));
        assertThat(json.readTree(json.writeValueAsString(client.cartDraft("M-1001", draft))))
                .isEqualTo(purchase);
        server.verify();
    }

    @Test
    void paymentAndPersonalPurchaseUseCheckoutScopeAndSharedFixtureRoundTrips() throws Exception {
        var all = json.readTree(Files.readString(Path.of("../../contracts/core/fixtures/checkout-payment.json")));
        for (String name : new String[] {"CheckoutPayment", "CheckoutPurchase", "CheckoutPaymentLookup"}) {
            String uri = name.equals("CheckoutPayment")
                    ? "/drafts/owned/payment"
                    : name.equals("CheckoutPurchase")
                            ? "/purchases/draft%3A00000000-0000-4000-8000-000000004001?merchant_id=M-1001&customer_id=trusted"
                            : "/drafts/owned/payment?merchant_id=M-1001&customer_id=trusted";
            server.expect(requestTo("http://commerce.test/internal/v1/shop" + uri))
                    .andExpect(req -> {
                        var identity = codec.verifyAsService(
                                req.getHeaders().getFirst("Authorization").substring(7), Instant.now());
                        assertThat(identity.subject()).isEqualTo("case-service");
                        assertThat(identity.scopes()).containsExactly("commerce:checkout");
                    })
                    .andRespond(withSuccess(all.get(name).toString(), MediaType.APPLICATION_JSON));
        }
        assertThat(json.readTree(
                        json.writeValueAsString(client.pay("owned", new PayCommand("M-1001", "trusted", "original")))))
                .isEqualTo(all.get("CheckoutPayment"));
        assertThat(json.readTree(json.writeValueAsString(
                        client.purchase("draft:00000000-0000-4000-8000-000000004001", "M-1001", "trusted"))))
                .isEqualTo(all.get("CheckoutPurchase"));
        assertThat(json.readTree(json.writeValueAsString(client.payment("owned", "M-1001", "trusted"))))
                .isEqualTo(all.get("CheckoutPaymentLookup"));
        server.verify();
    }

    @Test
    void draftUsesDedicatedCaseDeploymentScopeAndSharedFixtureRoundTrips() throws Exception {
        String body = fixture("ShopDraft");
        server.expect(requestTo("http://commerce.test/internal/v1/shop/drafts"))
                .andExpect(method(HttpMethod.POST))
                .andExpect(req -> {
                    var identity = codec.verifyAsService(
                            req.getHeaders().getFirst("Authorization").substring(7), Instant.now());
                    assertThat(identity.subject()).isEqualTo("case-service");
                    assertThat(identity.scopes()).containsExactly("commerce:checkout");
                })
                .andRespond(withSuccess(body, MediaType.APPLICATION_JSON));
        var actual = client.create(
                new DraftCommand("M-1001", "trusted-customer", "key", new DraftRequest("SKU-1001-BLACK", 2, 1L)));
        assertThat(json.readTree(json.writeValueAsString(actual))).isEqualTo(json.readTree(body));
        server.verify();
    }

    @Test
    void publicProductAndQuoteFixturesUseReadScopeAndRoundTrip() throws Exception {
        for (var name : new String[] {"ShopProduct", "ShopQuote"}) {
            String url = name.equals("ShopProduct") ? "/products/P-1001" : "/quote";
            server.expect(requestTo("http://commerce.test/internal/v1/shop" + url))
                    .andExpect(req -> assertThat(codec.verifyAsService(
                                            req.getHeaders()
                                                    .getFirst("Authorization")
                                                    .substring(7),
                                            Instant.now())
                                    .scopes())
                            .containsExactly("commerce:read"))
                    .andRespond(withSuccess(fixture(name), MediaType.APPLICATION_JSON));
        }
        assertThat(json.readTree(json.writeValueAsString(client.product("P-1001"))))
                .isEqualTo(json.readTree(fixture("ShopProduct")));
        assertThat(json.readTree(json.writeValueAsString(client.quote(new QuoteRequest("SKU-1001-BLACK", 2)))))
                .isEqualTo(json.readTree(fixture("ShopQuote")));
        server.verify();
    }

    @Test
    void explicitPriceConflictRemains409WhileUnavailableIs503NotMissing() {
        server.expect(requestTo("http://commerce.test/internal/v1/shop/quote"))
                .andRespond(
                        withStatus(HttpStatus.CONFLICT)
                                .contentType(MediaType.APPLICATION_JSON)
                                .body(
                                        "{\"code\":\"PRICE_CHANGED\",\"message\":\"changed\",\"retryable\":false,\"trace_id\":\"demo\",\"details\":{}}"));
        assertThatThrownBy(() -> client.quote(new QuoteRequest("sku", 1)))
                .isInstanceOf(CommerceShoppingClient.Refused.class)
                .satisfies(e ->
                        assertThat(((CommerceShoppingClient.Refused) e).status).isEqualTo(409));
        server.verify();
        server.reset();
        server.expect(requestTo("http://commerce.test/internal/v1/shop/products/p"))
                .andRespond(withServerError());
        assertThatThrownBy(() -> client.product("p")).isInstanceOf(CommerceUnavailableException.class);
        server.verify();
    }

    @Test
    void fulfillmentWireUsesDistinctMerchantAndBuyerScopesAndPreservesOriginalCommand() throws Exception {
        var all = json.readTree(Files.readString(Path.of("../../contracts/core/fixtures/fulfillment.json")));
        var scopes = new String[] {
            "commerce:fulfillment", "commerce:fulfillment", "commerce:fulfillment", "commerce:checkout"
        };
        var urls = new String[] {
            "/merchant/orders?merchant_id=M-1001&status=NOT_SHIPPED&limit=1",
            "/merchant/orders/order?merchant_id=M-1001",
            "/merchant/orders/order/simulated-shipment",
            "/shop/orders/order/fulfillment?merchant_id=M-1001&customer_id=trusted"
        };
        var results = new String[] {"MerchantTrades", "MerchantTrade", "OrderFulfillment", "OrderFulfillment"};
        for (int i = 0; i < urls.length; i++) {
            String scope = scopes[i];
            var expectation = server.expect(requestTo("http://commerce.test/internal/v1" + urls[i]))
                    .andExpect(req -> {
                        var identity = codec.verifyAsService(
                                req.getHeaders().getFirst("Authorization").substring(7), Instant.now());
                        assertThat(identity.subject()).isEqualTo("case-service");
                        assertThat(identity.scopes()).containsExactly(scope);
                    });
            if (i == 2)
                expectation
                        .andExpect(method(HttpMethod.POST))
                        .andExpect(content()
                                .json(all.get("SimulatedShipmentCommand").toString()));
            expectation.andRespond(withSuccess(all.get(results[i]).toString(), MediaType.APPLICATION_JSON));
        }
        assertThat(json.readTree(json.writeValueAsString(client.merchantOrders("M-1001", "NOT_SHIPPED", null, 1))))
                .isEqualTo(all.get("MerchantTrades"));
        assertThat(json.readTree(json.writeValueAsString(client.merchantOrder("order", "M-1001"))))
                .isEqualTo(all.get("MerchantTrade"));
        var command = json.treeToValue(
                all.get("SimulatedShipmentCommand"), com.resolveflow.shared.shopping.FulfillmentWire.ShipCommand.class);
        assertThat(json.readTree(json.writeValueAsString(client.ship("order", command))))
                .isEqualTo(all.get("OrderFulfillment"));
        assertThat(json.readTree(json.writeValueAsString(client.fulfillment("order", "M-1001", "trusted"))))
                .isEqualTo(all.get("OrderFulfillment"));
        server.verify();
    }
}
