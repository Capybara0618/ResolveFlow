package com.resolveflow.caseservice.order;

import com.resolveflow.shared.security.AuthenticatedPrincipal;
import com.resolveflow.shared.security.JwtCodec;
import com.resolveflow.shared.security.Role;
import java.time.Instant;
import java.util.List;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.http.HttpHeaders;
import org.springframework.stereotype.Component;
import org.springframework.web.client.RestClient;

/**
 * Case's relationship with Commerce, in one place.
 *
 * <p>Two things happen here that must not happen anywhere else:
 *
 * <ol>
 *   <li><b>The scope is derived from the verified principal.</b> {@code list} has no merchant or
 *       customer parameter a controller could accidentally fill from a request: the caller passes the
 *       principal, and the query is built from it. A crafted query cannot widen a scope that is never
 *       read from the query (docs/core-contracts.md:15).
 *   <li><b>Commerce is called with a service token, not the user's.</b> The public surface never
 *       forwards the user's bearer token to another service; Commerce trusts the service token and the
 *       scope Case derived (docs/core-contracts.md:26).
 * </ol>
 */
@Component
public class CommerceOrderLineClient {

    /** Raised when Commerce cannot answer; the API layer turns it into a 503, not a 404. */
    public static class CommerceUnavailableException extends RuntimeException {

        private static final long serialVersionUID = 1L;

        public CommerceUnavailableException(String message, Throwable cause) {
            super(message, cause);
        }
    }

    /** Raised when Commerce answers something this client does not understand. */
    public static class CommerceProtocolException extends RuntimeException {

        private static final long serialVersionUID = 1L;

        public CommerceProtocolException(String message) {
            super(message);
        }
    }

    private final RestClient rest;
    private final JwtCodec codec;
    private final String serviceName;

    public CommerceOrderLineClient(
            RestClient.Builder builder,
            JwtCodec jwtCodec,
            @Value("${resolveflow.commerce.base-url}") String baseUrl,
            @Value("${resolveflow.identity.service-name:case-service}") String serviceName) {
        this.rest = builder.baseUrl(baseUrl).build();
        this.codec = jwtCodec;
        this.serviceName = serviceName;
    }

    /** One page of the order lines this principal may see, newest first. */
    public OrderLinePage list(AuthenticatedPrincipal principal, String orderId, String cursor, Integer limit) {
        return fetch(principal, orderId, cursor, limit);
    }

    /**
     * The lines of one order, if it belongs to this principal.
     *
     * <p>Narrowing happens on Commerce's side inside the same scope, so an order that is not the
     * caller's comes back as an empty page. The empty page is what lets the caller answer 404 without
     * disclosing that the order exists at all (docs/core-contracts.md:27).
     */
    public OrderLinePage readOrder(AuthenticatedPrincipal principal, String orderId) {
        return fetch(principal, orderId, null, null);
    }

    private OrderLinePage fetch(AuthenticatedPrincipal principal, String orderId, String cursor, Integer limit) {
        try {
            OrderLinePage page = rest.get()
                    .uri(uriBuilder -> {
                        var builder = uriBuilder
                                .path("/internal/v1/order-lines")
                                .queryParam("merchant_id", principal.merchantId());
                        if (principal.role() == Role.CUSTOMER) {
                            builder.queryParam("customer_id", principal.customerId());
                        }
                        if (orderId != null && !orderId.isBlank()) {
                            builder.queryParam("order_id", orderId);
                        }
                        if (cursor != null && !cursor.isBlank()) {
                            builder.queryParam("cursor", cursor);
                        }
                        if (limit != null) {
                            builder.queryParam("limit", limit);
                        }
                        return builder.build();
                    })
                    .header(HttpHeaders.AUTHORIZATION, "Bearer " + serviceToken())
                    .retrieve()
                    .body(OrderLinePage.class);
            if (page == null) {
                throw new CommerceProtocolException("commerce returned an empty body");
            }
            return page;
        } catch (CommerceProtocolException error) {
            throw error;
        } catch (RuntimeException error) {
            throw new CommerceUnavailableException("commerce could not answer the order-line read", error);
        }
    }

    private String serviceToken() {
        return codec.issueServiceToken(serviceName, Instant.now());
    }

    /**
     * The wire shape of Commerce's listing, which is the same shape the public view returns.
     *
     * <p>Unknown members are refused by this service's Jackson configuration, so a Commerce that
     * starts sending extra fields is a loud failure here rather than a silent pass-through.
     */
    public record OrderLinePage(List<OrderLineSummary> items, PageMeta page) {}

    public record OrderLineSummary(
            @com.fasterxml.jackson.annotation.JsonProperty("order_id")
            String orderId,

            @com.fasterxml.jackson.annotation.JsonProperty("line_id")
            String lineId,

            String sku,
            String category,
            int quantity,

            @com.fasterxml.jackson.annotation.JsonProperty("line_paid_amount")
            long linePaidAmount,

            String currency,

            @com.fasterxml.jackson.annotation.JsonProperty("paid_at")
            Instant paidAt,

            String status,
            long version) {}

    public record PageMeta(
            @com.fasterxml.jackson.annotation.JsonProperty("next_cursor")
            String nextCursor,

            int limit) {}
}
