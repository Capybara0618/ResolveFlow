package com.resolveflow.caseservice.shopping;

import static org.assertj.core.api.Assertions.*;

import com.resolveflow.caseservice.CaseDatabaseTest;
import com.resolveflow.caseservice.order.OrderController;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.resttestclient.autoconfigure.AutoConfigureRestTestClient;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.context.ApplicationContext;
import org.springframework.test.web.servlet.client.RestTestClient;

@AutoConfigureRestTestClient
@SpringBootTest(
        webEnvironment = SpringBootTest.WebEnvironment.RANDOM_PORT,
        properties = "resolveflow.compat.commerce-facade-enabled=false")
class CommerceFacadeDisabledTest extends CaseDatabaseTest {
    @Autowired
    ApplicationContext context;

    @Autowired
    RestTestClient rest;

    @Test
    void normalCaseProcessDoesNotPublishMigratedCommerceControllers() {
        for (Class<?> type : new Class<?>[] {
            ShopController.class,
            CartController.class,
            CheckoutController.class,
            MerchantTradeController.class,
            CatalogAdminController.class,
            ProductReviewController.class,
            OrderController.class,
            LegacyPublicPresentationController.class
        }) {
            assertThat(context.getBeansOfType(type)).isEmpty();
        }
        for (String path : new String[] {
            "/api/v1/shop/products",
            "/api/v1/shop/cart",
            "/api/v1/orders",
            "/api/v1/merchant/orders",
            "/api/v1/merchant/products",
            "/api/v1/shop/products/P-1001/presentation"
        }) rest.get().uri(path).exchange().expectStatus().isNotFound();
        assertThat(context.getBean(com.resolveflow.caseservice.order.CommerceOrderLineClient.class))
                .isNotNull();
        assertThat(context.getBean(com.resolveflow.caseservice.auth.IdentityAccessController.class))
                .isNotNull();
        assertThat(context.getBean(PresentationController.class)).isNotNull();
    }
}
