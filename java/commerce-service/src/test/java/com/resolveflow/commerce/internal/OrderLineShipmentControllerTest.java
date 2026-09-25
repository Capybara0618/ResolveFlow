package com.resolveflow.commerce.internal;

import static org.assertj.core.api.Assertions.assertThat;

import com.resolveflow.commerce.CommerceDatabaseTest;
import com.resolveflow.shared.security.JwtCodec;
import com.resolveflow.shared.security.ServiceScopes;
import java.time.Duration;
import java.time.Instant;
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
 * {@code GET /internal/v1/order-lines/{line_id}/shipment} over HTTP (C06.2a).
 *
 * <p>Logistics in this core are a **simulator** (docs/core-scope.md:30), and the contract makes that a
 * required, constant member rather than a note in a README: {@code synthetic: true}
 * (contracts/core/openapi-commerce.yaml:500). The test asserts the marker first and by name, because a
 * response that read like a real carrier integration is the failure this whole surface exists to avoid — a
 * reviewer has to be able to tell simulated evidence from a real carrier's.
 *
 * <p>The rest is the shape a citation is checked against: a line id, a status, a carrier conclusion from the
 * contract's four values, the events with their own source versions, and the one version that says which
 * snapshot this is. {@code source_version} is the maximum event version rather than a count, so a late event
 * that arrives with a lower version can be recognised instead of overwriting newer state.
 */
@SpringBootTest(webEnvironment = SpringBootTest.WebEnvironment.RANDOM_PORT)
@AutoConfigureRestTestClient
class OrderLineShipmentControllerTest extends CommerceDatabaseTest {

    private static final ObjectMapper MAPPER = new ObjectMapper();

    /** The line the core OpenAPI examples use, and the one the demo case is about. */
    private static final String LOST_LINE = "7001";

    @Autowired
    RestTestClient rest;

    @Autowired
    JdbcTemplate jdbc;

    @Value("${resolveflow.identity.jwt.secret}")
    String secret;

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

    private RestTestClient.ResponseSpec shipment(String lineId, String token) {
        return rest.get()
                .uri("/internal/v1/order-lines/" + lineId + "/shipment")
                .header("Authorization", "Bearer " + token)
                .exchange();
    }

    private JsonNode readShipment(String lineId) {
        return MAPPER.readTree(shipment(lineId, serviceToken())
                .expectStatus()
                .isOk()
                .expectBody(String.class)
                .returnResult()
                .getResponseBody());
    }

    @Test
    @DisplayName("the shipment says it is synthetic, and the marker is the contract's constant true")
    void theShipmentIsLabelledSynthetic() {
        JsonNode body = readShipment(LOST_LINE);

        // Required and constant. If this is ever relaxed, the distinction between simulated logistics and a
        // real carrier integration disappears from the wire, and only the docs would still say so.
        assertThat(body.has("synthetic")).isTrue();
        assertThat(body.get("synthetic").isBoolean()).isTrue();
        assertThat(body.get("synthetic").booleanValue()).isTrue();
    }

    @Test
    @DisplayName("the shipment is the contract's members, member for member")
    void theShipmentIsTheContractShape() {
        JsonNode body = readShipment(LOST_LINE);

        // Exactly the seven declared members: an extra member is a protocol error on a schema that declares
        // additionalProperties: false.
        assertThat(body.propertyNames())
                .containsExactlyInAnyOrder(
                        "line_id",
                        "synthetic",
                        "status",
                        "carrier_conclusion",
                        "events",
                        "source_version",
                        "updated_at");
        assertThat(body.get("line_id").stringValue()).isEqualTo(LOST_LINE);
        assertThat(body.get("status").stringValue()).isNotBlank();
        assertThat(body.get("carrier_conclusion").stringValue()).isIn("LOST", "DELIVERED", "IN_TRANSIT", "UNKNOWN");
        assertThat(body.get("source_version").isNumber()).isTrue();
        assertThat(body.get("source_version").asLong()).isGreaterThanOrEqualTo(1);
        assertThat(Instant.parse(body.get("updated_at").stringValue())).isNotNull();

        JsonNode events = body.get("events");
        assertThat(events.isArray()).isTrue();
        assertThat(events.size()).isGreaterThanOrEqualTo(1);
        assertThat(events.size()).isLessThanOrEqualTo(200);
        for (JsonNode event : events) {
            assertThat(event.propertyNames()).containsExactlyInAnyOrder("code", "occurred_at", "source_version");
            assertThat(event.get("code").stringValue()).isNotBlank();
            assertThat(event.get("source_version").asLong()).isGreaterThanOrEqualTo(1);
            assertThat(Instant.parse(event.get("occurred_at").stringValue())).isNotNull();
        }
    }

    @Test
    @DisplayName("each line reads its own conclusion, and all four contract values occur")
    void theCarrierConclusionIsReadPerLine() {
        // A route that answered one constant would pass a single-line shape test and be useless to a citation
        // check. The seed covers every value the contract allows (openapi-commerce.yaml CarrierConclusion), so
        // "the four are all reachable" is asserted rather than assumed: a narrowed enum would show up here.
        assertThat(readShipment("7001").get("carrier_conclusion").stringValue()).isEqualTo("LOST");
        assertThat(readShipment("7002").get("carrier_conclusion").stringValue()).isEqualTo("IN_TRANSIT");
        assertThat(readShipment("7101").get("carrier_conclusion").stringValue()).isEqualTo("DELIVERED");
        assertThat(readShipment("7201").get("carrier_conclusion").stringValue()).isEqualTo("UNKNOWN");

        // Two lines with opposite terminal conclusions have different statuses too: the status is this
        // simulator's own word, and copying the conclusion into it would make the two members redundant.
        assertThat(readShipment("7001").get("status").stringValue())
                .isNotEqualTo(readShipment("7101").get("status").stringValue());
    }

    @Test
    @DisplayName("a shipment that exists always carries events, so the story is never empty")
    void aShipmentCarriesItsEvents() {
        for (String lineId : new String[] {"7001", "7002", "7101", "7201"}) {
            JsonNode events = readShipment(lineId).get("events");
            assertThat(events.size()).as("events for line " + lineId).isGreaterThanOrEqualTo(1);
        }
    }

    @Test
    @DisplayName("source_version is the newest event's version, not a count of events")
    void theSourceVersionIsTheNewestEventVersion() {
        JsonNode body = readShipment(LOST_LINE);

        long newest = 0;
        int count = 0;
        for (JsonNode event : body.get("events")) {
            newest = Math.max(newest, event.get("source_version").asLong());
            count++;
        }
        // A count would equal the number of events; a version is what a late event is compared against, and
        // the two are different numbers as soon as a version is skipped (which the seed does on purpose).
        assertThat(body.get("source_version").asLong()).isEqualTo(newest);
        assertThat(count).isGreaterThan(0);
    }

    @Test
    @DisplayName("an unknown line is 404 and a user token is refused")
    void theRouteIsServiceScoped() {
        shipment("999999", serviceToken()).expectStatus().isNotFound();
        // The shipment carries carrier conclusions the customer never sees in this protocol, so the route is
        // internal: a user token is refused by the service filter, not merely ignored.
        shipment(LOST_LINE, userToken()).expectStatus().isForbidden();
    }

    @Test
    @DisplayName("a line with no shipment is 404 rather than an invented empty snapshot")
    void aLineWithoutAShipmentIsNotFound() {
        // Every seeded line has one, so a line that exists in the read model but has no shipment row is the
        // honest way to test this: the answer must be "no such shipment", never a snapshot with empty events
        // and a conclusion the carrier never made.
        jdbc.update("DELETE FROM shipment_event WHERE line_id = '7002'");
        jdbc.update("DELETE FROM shipment WHERE line_id = '7002'");

        try {
            shipment("7002", serviceToken()).expectStatus().isNotFound();
        } finally {
            jdbc.update("INSERT INTO shipment (line_id, status, carrier_conclusion, source_version)"
                    + " VALUES ('7002', 'IN_TRANSIT', 'IN_TRANSIT', 2)");
            jdbc.update("INSERT INTO shipment_event (line_id, code, occurred_at, source_version) VALUES"
                    + " ('7002', 'SHIPMENT_CREATED', '2026-09-10 12:00:00.000000', 1),"
                    + " ('7002', 'IN_TRANSIT', '2026-09-11 09:00:00.000000', 2)");
        }
    }
}
