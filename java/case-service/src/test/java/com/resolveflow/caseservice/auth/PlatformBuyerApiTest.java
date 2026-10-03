package com.resolveflow.caseservice.auth;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

import com.resolveflow.caseservice.CaseDatabaseTest;
import com.resolveflow.caseservice.casefile.CaseRepository;
import com.resolveflow.caseservice.order.CommerceOrderLineClient;
import com.resolveflow.shared.pagination.OrderReadCursor;
import com.resolveflow.shared.security.AuthenticatedPrincipal;
import com.resolveflow.shared.security.JwtCodec;
import com.resolveflow.shared.security.Role;
import java.time.Instant;
import java.util.ArrayList;
import java.util.Comparator;
import java.util.List;
import java.util.Map;
import java.util.Optional;
import java.util.UUID;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.resttestclient.autoconfigure.AutoConfigureRestTestClient;
import org.springframework.boot.test.context.TestConfiguration;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Primary;
import org.springframework.dao.DataIntegrityViolationException;
import org.springframework.http.MediaType;
import org.springframework.test.web.servlet.client.RestTestClient;
import org.springframework.web.client.RestClient;
import tools.jackson.databind.JsonNode;
import tools.jackson.databind.ObjectMapper;

/** Real identity/mapping/case MySQL + HTTP; Commerce is a scoped stub, not evidence of checkout/payment. */
@AutoConfigureRestTestClient
class PlatformBuyerApiTest extends CaseDatabaseTest {
    @Autowired
    RestTestClient rest;

    @Autowired
    JwtCodec codec;

    @Autowired
    CaseRepository cases;

    @Autowired
    StubCommerce commerce;

    private final ObjectMapper json = new ObjectMapper();

    @TestConfiguration
    static class Configuration {
        @Bean
        @Primary
        StubCommerce stub(RestClient.Builder builder, JwtCodec codec) {
            return new StubCommerce(builder, codec);
        }
    }

    static class StubCommerce extends CommerceOrderLineClient {
        final List<AuthenticatedPrincipal> seen = new ArrayList<>();
        boolean failSecondStore;

        StubCommerce(RestClient.Builder builder, JwtCodec codec) {
            super(builder, codec, "http://unused", "case-service");
        }

        private List<OrderLineSummary> owned(AuthenticatedPrincipal p) {
            seen.add(p);
            assertThat(p.isPlatformBuyer()).isFalse();
            if (failSecondStore && p.merchantId().equals("M-1002"))
                throw new CommerceUnavailableException("offline", null);
            if (p.merchantId().equals("M-1001") && p.customerId().equals("C-B3001-M1001"))
                return List.of(line("A1", "M-1001", 458), line("A2", "M-1001", 456));
            if (p.merchantId().equals("M-1002") && p.customerId().equals("C-B3001-M1002"))
                return List.of(line("B1", "M-1002", 457));
            return List.of();
        }

        static OrderLineSummary line(String id, String merchant, int micros) {
            return new OrderLineSummary(
                    merchant.equals("M-1001")
                            ? "00000000-0000-4000-8000-000000003001"
                            : "00000000-0000-4000-8000-000000003002",
                    id,
                    "SKU-DEMO",
                    "合成商品",
                    "黑色",
                    "electronics",
                    1,
                    32900,
                    "CNY",
                    Instant.parse("2026-09-20T08:00:00.123" + micros + "Z"),
                    "PAID",
                    1);
        }

        @Override
        public OrderLinePage list(AuthenticatedPrincipal p, String order, String cursor, Integer requested) {
            int limit = requested == null ? 20 : requested;
            var after = OrderReadCursor.decode(cursor);
            var rows = owned(p).stream()
                    .filter(line -> after == null
                            || line.paidAt().isBefore(after.paidAt())
                            || (line.paidAt().equals(after.paidAt())
                                    && line.lineId().compareTo(after.lineId()) < 0))
                    .sorted(Comparator.comparing(OrderLineSummary::paidAt)
                            .thenComparing(OrderLineSummary::lineId)
                            .reversed())
                    .toList();
            var items = rows.stream().limit(limit).toList();
            String next = rows.size() > limit
                    ? new OrderReadCursor(
                                    items.getLast().paidAt(), items.getLast().lineId())
                            .encode()
                    : null;
            return new OrderLinePage(items, new PageMeta(next, limit));
        }

        @Override
        public OrderLinePage readOrder(AuthenticatedPrincipal p, String id) {
            return new OrderLinePage(
                    owned(p).stream().filter(line -> line.orderId().equals(id)).toList(), new PageMeta(null, 20));
        }

        @Override
        public OrderLinePage listByLine(AuthenticatedPrincipal p, String id) {
            return new OrderLinePage(
                    owned(p).stream().filter(line -> line.lineId().equals(id)).toList(), new PageMeta(null, 1));
        }

        @Override
        public Optional<LineContext> readLineContext(String id) {
            if (!List.of("A1", "A2", "B1").contains(id)) return Optional.empty();
            String merchant = id.startsWith("A") ? "M-1001" : "M-1002";
            var line = line(id, merchant, 456);
            return Optional.of(new LineContext(
                    line.orderId(),
                    id,
                    merchant,
                    "C-B3001-" + merchant.replace("-", ""),
                    line.sku(),
                    line.category(),
                    1,
                    32900,
                    0,
                    0,
                    "CNY",
                    line.paidAt(),
                    "PAID",
                    1));
        }
    }

    @BeforeEach
    void clear() {
        deleteAllCaseData(jdbc);
        commerce.seen.clear();
        commerce.failSecondStore = false;
    }

    @AfterEach
    void restore() {
        jdbc.update("DELETE FROM buyer_customer_binding WHERE buyer_id='B-other'");
        jdbc.update("DELETE FROM platform_buyer WHERE buyer_id='B-other'");
        jdbc.update("UPDATE identity_account SET enabled=TRUE,identity_version=0 WHERE username='demo-buyer'");
        jdbc.update("UPDATE identity_merchant SET enabled=TRUE WHERE merchant_id='M-1002'");
    }

    private String login(String username, String password) {
        var body = rest.post()
                .uri("/api/v1/auth/login")
                .contentType(MediaType.APPLICATION_JSON)
                .body(Map.of("username", username, "password", password))
                .exchange()
                .expectStatus()
                .isOk()
                .expectBody(String.class)
                .returnResult()
                .getResponseBody();
        return json.readTree(body).get("access_token").stringValue();
    }

    private String buyer() {
        return login("demo-buyer", "demo-pass-4001");
    }

    private JsonNode read(String path, String token) {
        return json.readTree(rest.get()
                .uri(path)
                .header("Authorization", "Bearer " + token)
                .exchange()
                .expectStatus()
                .isOk()
                .expectBody(String.class)
                .returnResult()
                .getResponseBody());
    }

    private String row(String merchant, String customer, String status, Instant time) {
        String id = UUID.randomUUID().toString();
        cases.insertCase(
                id,
                merchant,
                customer,
                UUID.randomUUID().toString(),
                "line-" + id,
                "原始申请",
                status,
                1,
                1,
                null,
                time,
                time);
        return id;
    }

    @Test
    void oneLoginHasNoMerchantAndNeverInheritsLegacyCustomerOrders() {
        String token = buyer();
        var profile = read("/api/v1/auth/me", token);
        assertThat(profile.get("buyer_id").stringValue()).isEqualTo("B-3001");
        assertThat(profile.has("merchant_id")).isFalse();
        assertThat(profile.has("customer_id")).isFalse();
        var page = read("/api/v1/orders?merchant_id=M-OTHER&customer_id=C-2002&scope=all", token);
        assertThat(page.get("items")).hasSize(3);
        assertThat(page.get("items").get(0).get("merchant_id").stringValue()).isEqualTo("M-1001");
        assertThat(page.get("items").get(1).get("merchant_id").stringValue()).isEqualTo("M-1002");
        assertThat(commerce.seen).allSatisfy(p -> {
            assertThat(p.subject()).isEqualTo("demo-buyer");
            assertThat(p.customerId()).startsWith("C-B3001-");
        });
        String forged = codec.issue(
                new AuthenticatedPrincipal("demo-buyer", "M-1001", Role.CUSTOMER, "C-B3001-M1001"), Instant.now());
        rest.get()
                .uri("/api/v1/auth/me")
                .header("Authorization", "Bearer " + forged)
                .exchange()
                .expectStatus()
                .isUnauthorized();
        String wrongBuyer = codec.issue(
                new AuthenticatedPrincipal("demo-buyer", null, Role.CUSTOMER, null, "B-other"), Instant.now());
        rest.get()
                .uri("/api/v1/auth/me")
                .header("Authorization", "Bearer " + wrongBuyer)
                .exchange()
                .expectStatus()
                .isUnauthorized();
    }

    @Test
    void globalOrderCursorDoesNotSkipMicrosecondsAndDownstreamFailureIsNotAPartialSuccess() {
        String token = buyer(), cursor = null;
        var ids = new ArrayList<String>();
        do {
            var page = read("/api/v1/orders?limit=1" + (cursor == null ? "" : "&cursor=" + cursor), token);
            ids.add(page.get("items").get(0).get("line_id").stringValue());
            cursor = page.get("page").path("next_cursor").asString(null);
        } while (cursor != null);
        assertThat(ids).containsExactly("A1", "B1", "A2");
        cursor = read("/api/v1/orders?limit=1", token)
                .get("page")
                .get("next_cursor")
                .stringValue();
        String modified = new String(
                        java.util.Base64.getUrlDecoder().decode(cursor), java.nio.charset.StandardCharsets.UTF_8)
                .replace("B-3001", "B-other");
        String other = java.util.Base64.getUrlEncoder()
                .withoutPadding()
                .encodeToString(modified.getBytes(java.nio.charset.StandardCharsets.UTF_8));
        rest.get()
                .uri("/api/v1/orders?cursor=" + other)
                .header("Authorization", "Bearer " + token)
                .exchange()
                .expectStatus()
                .isBadRequest();
        rest.get()
                .uri("/api/v1/orders/not-mine")
                .header("Authorization", "Bearer " + token)
                .exchange()
                .expectStatus()
                .isNotFound();
        commerce.failSecondStore = true;
        rest.get()
                .uri("/api/v1/orders")
                .header("Authorization", "Bearer " + token)
                .exchange()
                .expectStatus()
                .isEqualTo(503);
    }

    @Test
    void globalApplicationsUseCompositeOwnershipAndAllowOnlyOwnDetailAndMaterial() {
        var time = Instant.parse("2026-10-03T02:00:00.123456Z");
        String a = row("M-1001", "C-B3001-M1001", "QUEUED", time.plusNanos(1000));
        String b = row("M-1002", "C-B3001-M1002", "QUEUED", time);
        String collision = row("M-1002", "C-B3001-M1001", "QUEUED", time.plusSeconds(1));
        String legacy = row("M-1001", "C-2002", "QUEUED", time.plusSeconds(1));
        String token = buyer();
        var first = read("/api/v1/customer/cases?limit=1", token);
        assertThat(first.get("items").get(0).get("case_id").stringValue()).isEqualTo(a);
        String cursor = first.get("page").get("next_cursor").stringValue();
        assertThat(read("/api/v1/customer/cases?limit=1&cursor=" + cursor, token)
                        .toString())
                .contains(b)
                .doesNotContain(a, collision, legacy);
        assertThat(read("/api/v1/customer/cases/" + b, token)
                        .get("case")
                        .get("case_id")
                        .stringValue())
                .isEqualTo(b);
        for (String invisible : List.of(collision, legacy))
            for (String path : List.of("/api/v1/customer/cases/", "/api/v1/cases/"))
                rest.get()
                        .uri(path + invisible)
                        .header("Authorization", "Bearer " + token)
                        .exchange()
                        .expectStatus()
                        .isNotFound();
        rest.post()
                .uri("/api/v1/cases/" + b + "/evidence")
                .header("Authorization", "Bearer " + token)
                .contentType(MediaType.APPLICATION_JSON)
                .body(Map.of("evidence_kind", "CUSTOMER_STATEMENT", "text", "B店本人补充"))
                .exchange()
                .expectStatus()
                .isOk();
        assertThat(jdbc.queryForObject("SELECT input_revision FROM aftersale_case WHERE case_id=?", Integer.class, b))
                .isEqualTo(2);
        rest.post()
                .uri("/api/v1/cases/" + legacy + "/cancel")
                .header("Authorization", "Bearer " + token)
                .contentType(MediaType.APPLICATION_JSON)
                .body(Map.of("reason", "越权"))
                .exchange()
                .expectStatus()
                .isNotFound();
        assertThat(jdbc.queryForObject("SELECT status FROM aftersale_case WHERE case_id=?", String.class, legacy))
                .isEqualTo("QUEUED");
    }

    @Test
    void bothStoresCanOpenCasesWithTheirOwnPolicyAndSameIdempotencyKey() {
        String token = buyer();
        for (String line : List.of("A1", "B1")) {
            assertThat(read("/api/v1/customer/order-lines/" + line, token)
                            .get("can_apply")
                            .booleanValue())
                    .isTrue();
            String body = rest.post()
                    .uri("/api/v1/cases")
                    .header("Authorization", "Bearer " + token)
                    .header("Idempotency-Key", "same-key-across-stores")
                    .contentType(MediaType.APPLICATION_JSON)
                    .body(Map.of("line_id", line, "description", "物流显示包裹丢失", "requested_actions", List.of("REFUND")))
                    .exchange()
                    .expectStatus()
                    .isCreated()
                    .expectBody(String.class)
                    .returnResult()
                    .getResponseBody();
            String id = json.readTree(body).get("case_id").stringValue();
            String merchant = line.startsWith("A") ? "M-1001" : "M-1002";
            assertThat(jdbc.queryForObject("SELECT merchant_id FROM aftersale_case WHERE case_id=?", String.class, id))
                    .isEqualTo(merchant);
            assertThat(jdbc.queryForObject("SELECT customer_id FROM aftersale_case WHERE case_id=?", String.class, id))
                    .startsWith("C-B3001-");
            assertThat(jdbc.queryForObject(
                            "SELECT merchant_id FROM case_policy_manifest WHERE case_id=?", String.class, id))
                    .isEqualTo(merchant);
            rest.post()
                    .uri("/api/v1/cases/" + id + "/cancel")
                    .header("Authorization", "Bearer " + token)
                    .contentType(MediaType.APPLICATION_JSON)
                    .body(Map.of("reason", "合成测试撤销"))
                    .exchange()
                    .expectStatus()
                    .isOk();
        }
        rest.post()
                .uri("/api/v1/cases")
                .header("Authorization", "Bearer " + token)
                .header("Idempotency-Key", "not-mine")
                .contentType(MediaType.APPLICATION_JSON)
                .body(Map.of("line_id", "legacy", "description", "越权", "requested_actions", List.of("REFUND")))
                .exchange()
                .expectStatus()
                .isNotFound();
        assertThat(jdbc.queryForObject("SELECT COUNT(*) FROM aftersale_case", Integer.class))
                .isEqualTo(2);
    }

    @Test
    void merchantAdminsCannotListResetOrDisablePlatformBuyerAndBuyerCannotEnterReviewQueue() {
        String admin = login("demo-admin", "demo-pass-1100");
        assertThat(read("/api/v1/admin/accounts", admin).toString()).doesNotContain("demo-buyer", "B-3001");
        for (String suffix : List.of("", "/password")) {
            var body = suffix.isEmpty()
                    ? Map.of("display_name", "测试改名", "role", "REVIEWER", "enabled", false, "reason", "越权停用")
                    : Map.of("password", "another-demo-pass", "reason", "越权重置");
            rest.post()
                    .uri("/api/v1/admin/accounts/demo-buyer" + suffix)
                    .header("Authorization", "Bearer " + admin)
                    .header("If-Match", "\"1\"")
                    .contentType(MediaType.APPLICATION_JSON)
                    .body(body)
                    .exchange()
                    .expectStatus()
                    .isNotFound();
        }
        rest.get()
                .uri("/api/v1/review/cases")
                .header("Authorization", "Bearer " + buyer())
                .exchange()
                .expectStatus()
                .isForbidden();
    }

    @Test
    void accountRevisionAndDisabledMerchantApplyWithoutDisablingTheWholeBuyer() {
        String token = buyer();
        jdbc.update("UPDATE identity_merchant SET enabled=FALSE WHERE merchant_id='M-1002'");
        assertThat(read("/api/v1/auth/me", token).get("buyer_id").stringValue()).isEqualTo("B-3001");
        assertThat(read("/api/v1/orders", token).get("items")).hasSize(2);
        jdbc.update("UPDATE identity_account SET identity_version=identity_version+1 WHERE username='demo-buyer'");
        rest.get()
                .uri("/api/v1/orders")
                .header("Authorization", "Bearer " + token)
                .exchange()
                .expectStatus()
                .isUnauthorized();
        String current = buyer();
        jdbc.update("UPDATE identity_account SET enabled=FALSE WHERE username='demo-buyer'");
        rest.get()
                .uri("/api/v1/auth/me")
                .header("Authorization", "Bearer " + current)
                .exchange()
                .expectStatus()
                .isUnauthorized();
        rest.post()
                .uri("/api/v1/auth/login")
                .contentType(MediaType.APPLICATION_JSON)
                .body(Map.of("username", "demo-buyer", "password", "demo-pass-4001"))
                .exchange()
                .expectStatus()
                .isUnauthorized();
    }

    @Test
    void buyerAnswersTheCurrentQuestionInTheActualStoreAndCannotReuseStaleVersion() {
        String id = row("M-1002", "C-B3001-M1002", "WAITING_CUSTOMER", Instant.now());
        String question = UUID.randomUUID().toString();
        cases.insertTimeline(
                id,
                UUID.randomUUID().toString(),
                1,
                "QUESTION_REQUIRED",
                "{\"question_id\":\"" + question + "\",\"questions\":[{\"prompt\":\"请补充承运商反馈\"}]}",
                Instant.now(),
                1);
        String token = buyer();
        rest.post()
                .uri("/api/v1/customer/cases/" + id + "/answers")
                .header("Authorization", "Bearer " + token)
                .header("If-Match", "\"1\"")
                .contentType(MediaType.APPLICATION_JSON)
                .body(Map.of("question_id", question, "text", "B店承运商已确认包裹丢失"))
                .exchange()
                .expectStatus()
                .isOk();
        assertThat(read("/api/v1/customer/cases/" + id, token).toString()).contains("ANSWERED", "B店承运商已确认包裹丢失");
        assertThat(jdbc.queryForObject("SELECT input_revision FROM aftersale_case WHERE case_id=?", Integer.class, id))
                .isEqualTo(2);
        rest.post()
                .uri("/api/v1/customer/cases/" + id + "/answers")
                .header("Authorization", "Bearer " + token)
                .header("If-Match", "\"1\"")
                .contentType(MediaType.APPLICATION_JSON)
                .body(Map.of("question_id", question, "text", "重复回答"))
                .exchange()
                .expectStatus()
                .isEqualTo(409);
    }

    @Test
    void databaseRejectsHybridIdentityAndDuplicateCompositeOwner() {
        assertThatThrownBy(() ->
                        jdbc.update("UPDATE identity_account SET merchant_id='M-1001' WHERE username='demo-buyer'"))
                .isInstanceOf(org.springframework.dao.DataAccessException.class)
                .hasMessageContaining("ck_identity_binding");
        assertThatThrownBy(() -> jdbc.update("UPDATE identity_account SET role='REVIEWER' WHERE username='demo-buyer'"))
                .isInstanceOf(org.springframework.dao.DataAccessException.class)
                .hasMessageContaining("ck_identity_binding");
        jdbc.update("INSERT INTO platform_buyer (buyer_id) VALUES ('B-other')");
        assertThatThrownBy(
                        () -> jdbc.update(
                                "INSERT INTO buyer_customer_binding (buyer_id,merchant_id,customer_id) VALUES ('B-other','M-1001','C-B3001-M1001')"))
                .isInstanceOf(DataIntegrityViolationException.class)
                .hasMessageContaining("uq_buyer_resource_owner");
        assertThatThrownBy(
                        () -> jdbc.update(
                                "INSERT INTO buyer_customer_binding (buyer_id,merchant_id,customer_id) VALUES ('B-3001','M-1001','C-2002')"))
                .isInstanceOf(DataIntegrityViolationException.class);
        assertThat(jdbc.queryForObject(
                        "SELECT customer_id FROM identity_account WHERE username='demo-customer'", String.class))
                .isEqualTo("C-2002");
    }
}
