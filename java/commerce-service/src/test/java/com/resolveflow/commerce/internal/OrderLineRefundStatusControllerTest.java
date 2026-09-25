package com.resolveflow.commerce.internal;

import static org.assertj.core.api.Assertions.assertThat;

import com.resolveflow.commerce.CommerceDatabaseTest;
import com.resolveflow.shared.security.JwtCodec;
import com.resolveflow.shared.security.ServiceScopes;
import java.time.Duration;
import java.time.Instant;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.boot.resttestclient.autoconfigure.AutoConfigureRestTestClient;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.test.web.servlet.client.RestTestClient;
import tools.jackson.databind.JsonNode;
import tools.jackson.databind.ObjectMapper;

/**
 * {@code GET /internal/v1/order-lines/{line_id}/refund-status} over HTTP (C06.2c).
 *
 * <p>The contract described this route before anything implemented it, and C06.2b's `get_refund_status` tool had
 * nothing to read. What it must say is a view over two tables that already exist and disagree if copied:
 * {@code line_refund} holds the slot's {@code state}/{@code operation_id}/{@code version}, while the amounts come
 * from {@code order_line} and the order's {@code payment_ledger}.
 *
 * <p>The member this test is most about is the one that is **absent**. The refundable amount is deliberately not
 * returned (contracts/core/openapi-commerce.yaml readLineRefundStatus): it is paid minus refunded minus reserved,
 * and a stored or re-derived copy of a derived number is how two services start disagreeing about the same money.
 * An endpoint that helpfully added it would pass every shape check here and be the bug.
 *
 * <p>The amount figures are asserted **after moving them**, not against the seed's zeros: a route that answered
 * constants would pass a read of the demo data, and this one has to reflect the ledger.
 */
@SpringBootTest(webEnvironment = SpringBootTest.WebEnvironment.RANDOM_PORT)
@AutoConfigureRestTestClient
class OrderLineRefundStatusControllerTest extends CommerceDatabaseTest {

    private static final ObjectMapper MAPPER = new ObjectMapper();

    private static final String LINE = "7001";
    private static final String ORDER = "00000000-0000-4000-8000-0000000000aa";

    @Autowired
    RestTestClient rest;

    @Autowired
    JdbcTemplate jdbc;

    @Value("${resolveflow.identity.jwt.secret}")
    String secret;

    @AfterEach
    void restoreTheSlotAndLedger() {
        // The slot and the ledger are the money path (C05); this read must not be what changes them, so every
        // test that moves them puts them back.
        jdbc.update("UPDATE line_refund SET state = 'FREE', operation_id = NULL, version = 1 WHERE line_id = ?", LINE);
        jdbc.update(
                "UPDATE payment_ledger SET refunded_amount = 0, reserved_refund_amount = 0, version = 1"
                        + " WHERE order_id = ?",
                ORDER);
    }

    private String serviceToken() {
        // `commerce:read` is required as of AS02.3's security sub-step; a scopeless service token is now refused
        // on this service's internal read routes. See OrderLineContextControllerTest#serviceToken.
        return new JwtCodec(secret, Duration.ofHours(1))
                .issueServiceToken("case-service", null, null, ServiceScopes.COMMERCE_READ, Instant.now());
    }

    private String userToken() {
        return new JwtCodec(secret, Duration.ofHours(1))
                .issue(
                        new com.resolveflow.shared.security.AuthenticatedPrincipal(
                                "demo-customer", "M-1001", com.resolveflow.shared.security.Role.CUSTOMER, "C-2002"),
                        Instant.now());
    }

    private RestTestClient.ResponseSpec refundStatus(String lineId, String token) {
        return rest.get()
                .uri("/internal/v1/order-lines/" + lineId + "/refund-status")
                .header("Authorization", "Bearer " + token)
                .exchange();
    }

    private JsonNode readRefundStatus(String lineId) {
        return MAPPER.readTree(refundStatus(lineId, serviceToken())
                .expectStatus()
                .isOk()
                .expectBody(String.class)
                .returnResult()
                .getResponseBody());
    }

    @Test
    @DisplayName("the refund status is the contract's members, and no derived amount among them")
    void theRefundStatusIsTheContractShape() {
        JsonNode body = readRefundStatus(LINE);

        // operation_id is optional in the contract and so is not required here; the other eight are.
        assertThat(body.propertyNames())
                .contains(
                        "line_id",
                        "merchant_id",
                        "line_paid_amount",
                        "refunded_amount",
                        "reserved_refund_amount",
                        "currency",
                        "state",
                        "version")
                .doesNotContain("refundable_amount", "remaining_amount", "operation", "input_revision");
        assertThat(body.get("line_id").stringValue()).isEqualTo(LINE);
        assertThat(body.get("merchant_id").stringValue()).isEqualTo("M-1001");
        assertThat(body.get("currency").stringValue()).isEqualTo("CNY");
        assertThat(body.get("state").stringValue()).isIn("FREE", "RESERVED", "CONSUMED");
        assertThat(body.get("version").asLong()).isGreaterThanOrEqualTo(1);
    }

    @Test
    @DisplayName("the amounts come from the line and its order's ledger, not from constants")
    void theAmountsAreTheRealOnes() {
        // Move the order's money the way a reservation does, then read it back. The seed's zeros cannot tell a
        // working read from a hardcoded one; these numbers can.
        jdbc.update(
                "UPDATE payment_ledger SET refunded_amount = 1000, reserved_refund_amount = 800, version = 7"
                        + " WHERE order_id = ?",
                ORDER);

        JsonNode body = readRefundStatus(LINE);

        assertThat(body.get("line_paid_amount").asLong()).isEqualTo(2599);
        assertThat(body.get("refunded_amount").asLong()).isEqualTo(1000);
        assertThat(body.get("reserved_refund_amount").asLong()).isEqualTo(800);
    }

    @Test
    @DisplayName("a reserved line names the operation holding it, and the version is the slot's")
    void aReservedLineNamesItsOperation() {
        String operationId = "3f2504e0-4f89-41d3-9a0c-0305e82c3301";
        jdbc.update(
                "UPDATE line_refund SET state = 'RESERVED', operation_id = ?, version = 4 WHERE line_id = ?",
                operationId,
                LINE);

        JsonNode body = readRefundStatus(LINE);

        assertThat(body.get("state").stringValue()).isEqualTo("RESERVED");
        assertThat(body.get("operation_id").stringValue()).isEqualTo(operationId);
        // version is the slot's own version, which is what a decision is recorded against: the order line's
        // version would move for reasons unrelated to the refund.
        assertThat(body.get("version").asLong()).isEqualTo(4);
    }

    @Test
    @DisplayName("a free line has no operation, and the state says so rather than an empty id")
    void aFreeLineHasNoOperation() {
        JsonNode body = readRefundStatus(LINE);

        assertThat(body.get("state").stringValue()).isEqualTo("FREE");
        // The schema ties these together: `state = 'FREE'` iff `operation_id IS NULL`. A free line with an
        // operation id, or a reserved one without, would be a slot that cannot say who holds it.
        assertThat(body.has("operation_id")).isFalse();
    }

    @Test
    @DisplayName("the state narrows to the core three, so a deferred value is not representable")
    void theStateIsTheCoreThree() {
        // The compat model keeps IN_USE for the deferred cross-service protocol; core narrowed it away
        // (test_commerce_line_refund_state_narrows_the_compat_entitlement_enum asserts the same from the schema).
        jdbc.update(
                "UPDATE line_refund SET state = 'CONSUMED', operation_id = ?, version = 5 WHERE line_id = ?",
                "3f2504e0-4f89-41d3-9a0c-0305e82c3302",
                LINE);

        assertThat(readRefundStatus(LINE).get("state").stringValue()).isEqualTo("CONSUMED");
    }

    @Test
    @DisplayName("an unknown line is 404 and a user token is refused")
    void theRouteIsServiceScoped() {
        refundStatus("999999", serviceToken()).expectStatus().isNotFound();
        refundStatus(LINE, userToken()).expectStatus().isForbidden();
    }
}
