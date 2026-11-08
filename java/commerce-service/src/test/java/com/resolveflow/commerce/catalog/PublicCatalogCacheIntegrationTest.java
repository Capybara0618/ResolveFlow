package com.resolveflow.commerce.catalog;

import static org.assertj.core.api.Assertions.*;
import static org.mockito.ArgumentMatchers.*;
import static org.mockito.Mockito.*;

import com.resolveflow.commerce.CommerceDatabaseTest;
import com.resolveflow.shared.shopping.CheckoutWire.PayCommand;
import com.resolveflow.shared.shopping.ManagementWire;
import com.resolveflow.shared.shopping.PresentationWire;
import com.resolveflow.shared.shopping.ProductReviewWire;
import com.resolveflow.shared.shopping.ShoppingWire;
import java.time.Duration;
import java.util.List;
import java.util.Map;
import java.util.UUID;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.resttestclient.autoconfigure.AutoConfigureRestTestClient;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.test.context.DynamicPropertyRegistry;
import org.springframework.test.context.DynamicPropertySource;
import org.springframework.test.context.bean.override.mockito.MockitoSpyBean;
import org.springframework.test.web.servlet.client.RestTestClient;
import org.springframework.transaction.PlatformTransactionManager;
import org.springframework.transaction.support.TransactionTemplate;
import org.testcontainers.containers.GenericContainer;
import tools.jackson.databind.ObjectMapper;

/** Functional correctness against isolated MySQL/Redis and the public HTTP entry points. */
@SpringBootTest(
        webEnvironment = SpringBootTest.WebEnvironment.RANDOM_PORT,
        properties = {
            "resolveflow.catalog.cache-enabled=true", "resolveflow.product-reviews.cache-enabled=true",
            "resolveflow.product-reviews.rebuild-lock-enabled=true", "resolveflow.catalog.invalidation-poll-ms=600000"
        })
@AutoConfigureRestTestClient
class PublicCatalogCacheIntegrationTest {
    static final GenericContainer<?> REDIS = new GenericContainer<>("redis:7.4-alpine").withExposedPorts(6379);

    static {
        REDIS.start();
    }

    @DynamicPropertySource
    static void cacheProperties(DynamicPropertyRegistry registry) throws Exception {
        CommerceDatabaseTest.isolatedReadSchema(registry, "commerce_read_cache");
        registry.add("spring.data.redis.host", REDIS::getHost);
        registry.add("spring.data.redis.port", () -> REDIS.getMappedPort(6379));
    }

    @Autowired
    RestTestClient rest;

    @Autowired
    JdbcTemplate jdbc;

    @Autowired
    CatalogManagementService management;

    @Autowired
    PublicProductReadCache products;

    @Autowired
    ProductReviewReadCache reviewCache;

    @Autowired
    PublicCatalogCacheInvalidation invalidations;

    @Autowired
    CheckoutPayments payments;

    @Autowired
    StringRedisTemplate redis;

    @Autowired
    PlatformTransactionManager transactions;

    @MockitoSpyBean
    ShoppingService shopping;

    @MockitoSpyBean
    PresentationService presentation;

    @MockitoSpyBean
    ProductReviewService reviews;

    @MockitoSpyBean
    PublicCatalogCacheStore cache;

    ManagementWire.Product product;
    String store;
    final ObjectMapper json = new ObjectMapper();

    @BeforeEach
    void fixture() {
        store = "CACHE-" + UUID.randomUUID();
        management.sync(new ManagementWire.StoreSync(store, "公开缓存测试店", "隔离数据", true, 1));
        product = management.save(
                null,
                new ManagementWire.ProductCommand(
                        store,
                        "cache-test",
                        new ManagementWire.ProductWrite(
                                "原商品",
                                "原介绍",
                                "electronics",
                                "headphones",
                                true,
                                null,
                                List.of(new ManagementWire.SkuWrite(null, "黑色", 30000L, 10, true)))));
        invalidations.retryPending();
    }

    private String path() {
        return "/api/v1/shop/products/" + product.product_id();
    }

    private String get(String suffix, int status) {
        return rest.get()
                .uri(path() + suffix)
                .exchange()
                .expectStatus()
                .isEqualTo(status)
                .expectBody(String.class)
                .returnResult()
                .getResponseBody();
    }

    private ManagementWire.Product update(String name, long amount, boolean listed) {
        var current = management.read(store, product.product_id());
        return management.save(
                product.product_id(),
                new ManagementWire.ProductCommand(
                        store,
                        "cache-test",
                        new ManagementWire.ProductWrite(
                                name,
                                "更新介绍",
                                "electronics",
                                "headphones",
                                listed,
                                current.version(),
                                current.skus().stream()
                                        .map(s ->
                                                new ManagementWire.SkuWrite(s.sku_id(), s.variant(), amount, 10, true))
                                        .toList())));
    }

    @Test
    void publicHitsReadRedisWithoutCallingCatalogOrReviewDatabaseServices() {
        var detail = get("", 200);
        var media = get("/presentation", 200);
        var comments = get("/reviews", 200);
        clearInvocations(shopping, presentation, reviews);
        assertThat(get("", 200)).isEqualTo(detail);
        assertThat(get("/presentation", 200)).isEqualTo(media);
        assertThat(get("/reviews", 200)).isEqualTo(comments);
        verifyNoInteractions(shopping, presentation, reviews);
        assertThat(redis.getExpire(cache.productKey(product.product_id()))).isBetween(1L, 60L);
        assertThat(redis.getExpire(cache.reviewKey(product.product_id()))).isBetween(1L, 30L);
    }

    @Test
    void productUpdateInvalidatesPublicDataAndLateReadersCannotRefillOldData() {
        var old = products.product(product.product_id());
        var oldSnapshot = cache.read(cache.productKey(product.product_id()), product.product_id());
        update("新商品", 32000, true);
        assertThat(get("", 200)).contains("新商品", "32000");
        assertThat(cache.publish(
                        cache.productKey(product.product_id()),
                        product.product_id(),
                        oldSnapshot,
                        old,
                        Duration.ofSeconds(60)))
                .isFalse();
        assertThat(get("", 200)).contains("新商品");
        // Deliberately stale display data never changes checkout's authoritative quote.
        var current = cache.read(cache.productKey(product.product_id()), product.product_id());
        assertThat(cache.publish(
                        cache.productKey(product.product_id()),
                        product.product_id(),
                        current,
                        old,
                        Duration.ofSeconds(60)))
                .isTrue();
        var body = rest.post()
                .uri("/api/v1/shop/quote")
                .body(new ShoppingWire.QuoteRequest(product.skus().getFirst().sku_id(), 1))
                .exchange()
                .expectStatus()
                .isOk()
                .expectBody(String.class)
                .returnResult()
                .getResponseBody();
        assertThat(json.readTree(body).path("total_amount").asLong()).isEqualTo(32000);
    }

    @Test
    void productPresentationChangesInvalidateCoverAndPublicPresentation() {
        get("", 200);
        get("/presentation", 200);
        var image = UUID.randomUUID().toString();
        presentation.saveProduct(
                product.product_id(),
                new PresentationWire.ProductCommand(
                        store,
                        "cache-test",
                        new PresentationWire.ProductWrite(0L, List.of(image), List.of(), "新的发货说明", "售后说明", Map.of())));
        assertThat(get("", 200)).contains(image);
        assertThat(get("/presentation", 200)).contains(image, "新的发货说明");
    }

    @Test
    void delistingAndStoreDisablingInvalidateEveryAffectedPublicProjection() {
        get("", 200);
        get("/presentation", 200);
        get("/reviews", 200);
        update("已下架", 30000, false);
        get("", 404);
        get("/presentation", 404);
        get("/reviews", 404);
        update("重新上架", 30000, true);
        get("", 200);
        get("/presentation", 200);
        get("/reviews", 200);
        management.sync(new ManagementWire.StoreSync(store, "停用店", "隔离数据", false, 2));
        get("", 404);
        get("/presentation", 404);
        get("/reviews", 404);
    }

    @Test
    void reviewsAndRepliesInvalidateOnlyReviewDataAndRejectLateOldPublication() {
        var oldPage = reviewCache.read(product.product_id(), null, 10);
        var oldSnapshot = cache.read(cache.reviewKey(product.product_id()), product.product_id());
        get("", 200);
        String customer = "CACHE-BUYER-" + UUID.randomUUID();
        var draft = shopping.create(new ShoppingWire.DraftCommand(
                store,
                customer,
                UUID.randomUUID().toString(),
                new ShoppingWire.DraftRequest(product.skus().getFirst().sku_id(), 1, 1L)));
        var paid = payments.pay(
                draft.draftId(),
                new PayCommand(store, customer, UUID.randomUUID().toString()));
        jdbc.update(
                "UPDATE shipment SET status='DELIVERED',carrier_conclusion='DELIVERED' WHERE line_id=?", paid.lineId());
        var review = reviews.save(
                paid.lineId(),
                new ProductReviewWire.Command(store, customer, new ProductReviewWire.Write(5L, "新增评价", 0L)));
        assertThat(get("/reviews", 200)).contains("新增评价");
        assertThat(cache.publish(
                        cache.reviewKey(product.product_id()),
                        product.product_id(),
                        oldSnapshot,
                        oldPage,
                        Duration.ofSeconds(30)))
                .isFalse();
        clearInvocations(shopping);
        get("", 200);
        verifyNoInteractions(shopping);
        reviews.reply(
                review.reviewId(),
                new ProductReviewWire.ReplyCommand(store, new ProductReviewWire.Reply("商家已回复", review.version())));
        assertThat(get("/reviews", 200)).contains("商家已回复");
        var edited = reviews.save(
                paid.lineId(),
                new ProductReviewWire.Command(
                        store, customer, new ProductReviewWire.Write(4L, "修改后的评价", review.version() + 1)));
        assertThat(get("/reviews", 200)).contains("修改后的评价");
        assertThat(edited.rating()).isEqualTo(4);
    }

    @Test
    void rollbackKeepsOldCacheAndInvalidationFailureCommitsThenRetriesDurably() {
        get("", 200);
        String id = product.product_id();
        new TransactionTemplate(transactions).executeWithoutResult(status -> {
            update("应该回滚", 32000, true);
            status.setRollbackOnly();
        });
        assertThat(get("", 200)).contains("原商品").doesNotContain("应该回滚");
        assertThat(jdbc.queryForObject(
                        "SELECT COUNT(*) FROM public_catalog_cache_invalidation WHERE product_id=?", Integer.class, id))
                .isZero();
        doThrow(new IllegalStateException("isolated Redis outage")).when(cache).invalidate(eq(id), anyInt());
        update("已提交待失效", 35000, true);
        assertThat(management.read(store, id).name()).isEqualTo("已提交待失效");
        assertThat(jdbc.queryForObject(
                        "SELECT COUNT(*) FROM public_catalog_cache_invalidation WHERE product_id=?", Integer.class, id))
                .isEqualTo(1);
        doCallRealMethod().when(cache).invalidate(eq(id), anyInt());
        var restarted = new PublicCatalogCacheInvalidation(jdbc, cache, transactions, true, true);
        restarted.retryPending();
        assertThat(get("", 200)).contains("已提交待失效");
        assertThat(jdbc.queryForObject(
                        "SELECT COUNT(*) FROM public_catalog_cache_invalidation WHERE product_id=?", Integer.class, id))
                .isZero();
    }

    @Test
    void invalidPublicPayloadAndRedisFailureUseDatabaseWithoutMaskingMissingProducts() {
        String id = product.product_id();
        var page = products.product(id);
        var wrongProduct = json.readTree(json.writeValueAsString(page));
        ((tools.jackson.databind.node.ObjectNode) wrongProduct).put("product_id", "another-product");
        redis.opsForValue().set(cache.productKey(id), json.writeValueAsString(wrongProduct), Duration.ofSeconds(60));
        clearInvocations(shopping);
        assertThat(get("", 200)).contains(id, "原商品");
        verify(shopping).product(id);
        doThrow(new IllegalStateException("isolated Redis failure")).when(cache).read(anyString(), eq(id));
        assertThat(get("", 200)).contains(id);
        update("下架期间", 30000, false);
        get("", 404);
        doCallRealMethod().when(cache).read(anyString(), eq(id));
    }

    @Test
    void missingProductsDoNotCreatePersistentRedisGenerationKeys() {
        String missing = "CACHE-MISSING-" + UUID.randomUUID();
        for (String suffix : List.of("", "/presentation", "/reviews"))
            rest.get()
                    .uri("/api/v1/shop/products/" + missing + suffix)
                    .exchange()
                    .expectStatus()
                    .isNotFound();
        assertThat(redis.keys(cache.namespace() + ":aside-v2:*:" + missing)).isEmpty();
    }

    @Test
    void actualInFlightProductReadCannotRefillAfterACommittedUpdate() throws Exception {
        String id = product.product_id();
        var loaded = new java.util.concurrent.CountDownLatch(1);
        var release = new java.util.concurrent.CountDownLatch(1);
        doAnswer(invocation -> {
                    Object result = invocation.callRealMethod();
                    loaded.countDown();
                    if (!release.await(5, java.util.concurrent.TimeUnit.SECONDS))
                        throw new AssertionError("isolated reader was not released");
                    return result;
                })
                .when(shopping)
                .product(id);
        try (var pool = java.util.concurrent.Executors.newSingleThreadExecutor()) {
            var oldRead = pool.submit(() -> products.product(id));
            try {
                assertThat(loaded.await(3, java.util.concurrent.TimeUnit.SECONDS))
                        .isTrue();
                update("并发修改后的商品", 36000, true);
            } finally {
                release.countDown();
            }
            assertThat(oldRead.get(5, java.util.concurrent.TimeUnit.SECONDS).name())
                    .isEqualTo("原商品");
            assertThat(redis.hasKey(cache.productKey(id))).isFalse();
            doCallRealMethod().when(shopping).product(id);
            assertThat(get("", 200)).contains("并发修改后的商品", "36000");
        }
    }
}
