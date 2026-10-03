package com.resolveflow.caseservice.order;

import com.resolveflow.shared.security.AuthenticatedPrincipal;
import com.resolveflow.shared.security.JwtCodec;
import com.resolveflow.shared.security.Role;
import com.resolveflow.shared.security.ServiceScopes;
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

    /**
     * Raised when Commerce refuses the request itself (a 4xx).
     *
     * <p>Separate from {@link CommerceUnavailableException} because the two need opposite answers: an outage is
     * this service's problem and is worth retrying, while a refused request is the caller's and never will be.
     * The cursor on this route is the case that made it obvious — it is opaque and Commerce owns it
     * (docs/core-contracts.md:26), so this service cannot check it before sending it, and Commerce is the only
     * one that can say whether it is a page it ever issued (C05.4).
     */
    public static class CommerceRejectedQueryException extends RuntimeException {

        private static final long serialVersionUID = 1L;

        public CommerceRejectedQueryException(String message) {
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
        return fetch(principal, orderId, null, cursor, limit);
    }

    /**
     * The lines of one order, if it belongs to this principal.
     *
     * <p>Narrowing happens on Commerce's side inside the same scope, so an order that is not the
     * caller's comes back as an empty page. The empty page is what lets the caller answer 404 without
     * disclosing that the order exists at all (docs/core-contracts.md:27).
     */
    public OrderLinePage readOrder(AuthenticatedPrincipal principal, String orderId) {
        return fetch(principal, orderId, null, null, null);
    }

    /**
     * The lines of one line id inside the principal's scope, at most one row.
     *
     * <p>This is the "is this line mine?" question Case asks before opening a case. It is a scoped
     * read, not a check the caller performs: the scope again comes from the principal, and an empty
     * page is the only answer for a line the caller may not see (docs/core-contracts.md:28).
     */
    public OrderLinePage listByLine(AuthenticatedPrincipal principal, String lineId) {
        return fetch(principal, null, lineId, null, 1);
    }

    /**
     * One line's own amounts, by line id, for the re-check that recomputes a refund (C03.2a's route).
     *
     * <p>This is the one read that is not scoped by the principal: the contract declares it that way and the
     * scope check moves to the caller, which is why the response carries {@code merchant_id} and
     * {@code customer_id} — the caller confirms the line belongs to the case it is re-checking instead of
     * trusting that it does. An empty answer means Commerce does not have the line, which is a refusal this
     * service records rather than an outage it retries.
     */
    public java.util.Optional<LineContext> readLineContext(String lineId) {
        if (lineId == null || lineId.isBlank()) {
            throw new IllegalArgumentException("a line id is required to read a line context");
        }
        try {
            LineContext context = rest.get()
                    .uri("/internal/v1/order-lines/{lineId}/context", lineId)
                    .header(HttpHeaders.AUTHORIZATION, "Bearer " + serviceToken())
                    .retrieve()
                    .onStatus(status -> status.value() == 404, (request, response) -> {
                        throw new LineContextMissingException(lineId);
                    })
                    .body(LineContext.class);
            if (context == null) {
                throw new CommerceProtocolException("commerce returned an empty line context");
            }
            return java.util.Optional.of(context);
        } catch (LineContextMissingException error) {
            return java.util.Optional.empty();
        } catch (CommerceProtocolException error) {
            throw error;
        } catch (RuntimeException error) {
            throw new CommerceUnavailableException("commerce could not answer the line-context read", error);
        }
    }

    /** Raised internally for Commerce's 404 so it is not mistaken for an outage. */
    private static class LineContextMissingException extends RuntimeException {

        private static final long serialVersionUID = 1L;

        LineContextMissingException(String lineId) {
            super("commerce has no such order line: " + lineId);
        }
    }

    private OrderLinePage fetch(
            AuthenticatedPrincipal principal, String orderId, String lineId, String cursor, Integer limit) {
        if (principal.isPlatformBuyer()) {
            throw new IllegalArgumentException("Commerce reads require a trusted merchant/customer binding");
        }
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
                        if (lineId != null && !lineId.isBlank()) {
                            builder.queryParam("line_id", lineId);
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
                    // A 4xx means Commerce refused the request — the caller has to change something, and no
                    // amount of retrying will help (C05.4). 404 is deliberately excluded: Commerce answers an
                    // empty page for a scope that does not match (docs/core-contracts.md:27), so a 404 on this
                    // route is an anomaly rather than a caller error and stays an availability problem.
                    .onStatus(status -> status.is4xxClientError() && status.value() != 404, (request, response) -> {
                        throw new CommerceRejectedQueryException(
                                "commerce refused the order-line read with " + response.getStatusCode());
                    })
                    .body(OrderLinePage.class);
            if (page == null) {
                throw new CommerceProtocolException("commerce returned an empty body");
            }
            return page;
        } catch (CommerceProtocolException error) {
            throw error;
        } catch (CommerceRejectedQueryException error) {
            throw error;
        } catch (RuntimeException error) {
            throw new CommerceUnavailableException("commerce could not answer the order-line read", error);
        }
    }

    private String serviceToken() {
        // `commerce:read`, because Commerce's internal order-line routes now require it (AS02.3's security
        // sub-step added the check, and this is the caller that had to start asking). Before that step the token
        // carried no scope and Commerce accepted it, so the scope claim on the *tool* credential was the only place
        // the vocabulary appeared — a bound on the token that no route read.
        //
        // The string comes from ServiceScopes, which is also what Commerce's filter requires and what this service
        // mints onto a run's tool credential: one vocabulary, three call sites that cannot disagree.
        return codec.issueServiceToken(serviceName, null, null, ServiceScopes.COMMERCE_READ, Instant.now());
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

            // Optional presentation members (core OpenAPI OrderLineSummary). Nullable rather than
            // defaulted: a historical line has no product name, and a client that filled one in
            // would be inventing a product. Unknown members are still refused by this service's
            // Jackson configuration, so Commerce cannot add a third one silently.
            //
            // NON_NULL on these two **only**: an absent display field is omitted, the way
            // `next_cursor` is, so the public order view answers exactly as it did before V7. A
            // service-wide NON_NULL would also hide a null in a required member, which is a
            // protocol violation this service should pass on loudly rather than swallow.
            @com.fasterxml.jackson.annotation.JsonProperty("product_name")
            @com.fasterxml.jackson.annotation.JsonInclude(com.fasterxml.jackson.annotation.JsonInclude.Include.NON_NULL)
            String productName,

            @com.fasterxml.jackson.annotation.JsonProperty("variant_text")
            @com.fasterxml.jackson.annotation.JsonInclude(com.fasterxml.jackson.annotation.JsonInclude.Include.NON_NULL)
            String variantText,

            String category,
            int quantity,

            @com.fasterxml.jackson.annotation.JsonProperty("line_paid_amount")
            long linePaidAmount,

            String currency,

            @com.fasterxml.jackson.annotation.JsonProperty("paid_at")
            Instant paidAt,

            String status,
            long version,

            @com.fasterxml.jackson.annotation.JsonProperty("merchant_id")
            @com.fasterxml.jackson.annotation.JsonInclude(com.fasterxml.jackson.annotation.JsonInclude.Include.NON_NULL)
            String merchantId,

            @com.fasterxml.jackson.annotation.JsonProperty("merchant_name")
            @com.fasterxml.jackson.annotation.JsonInclude(com.fasterxml.jackson.annotation.JsonInclude.Include.NON_NULL)
            String merchantName,

            @com.fasterxml.jackson.annotation.JsonProperty("asset_key")
            @com.fasterxml.jackson.annotation.JsonInclude(com.fasterxml.jackson.annotation.JsonInclude.Include.NON_NULL)
            String assetKey) {
        public OrderLineSummary(
                String orderId,
                String lineId,
                String sku,
                String productName,
                String variantText,
                String category,
                int quantity,
                long linePaidAmount,
                String currency,
                Instant paidAt,
                String status,
                long version) {
            this(
                    orderId,
                    lineId,
                    sku,
                    productName,
                    variantText,
                    category,
                    quantity,
                    linePaidAmount,
                    currency,
                    paidAt,
                    status,
                    version,
                    null,
                    null,
                    null);
        }

        public OrderLineSummary withMerchant(String merchantId, String merchantName) {
            return new OrderLineSummary(
                    orderId,
                    lineId,
                    sku,
                    productName,
                    variantText,
                    category,
                    quantity,
                    linePaidAmount,
                    currency,
                    paidAt,
                    status,
                    version,
                    merchantId,
                    merchantName,
                    assetKey);
        }
    }

    /**
     * Commerce's authoritative line context: the paid amount, what has already been refunded or reserved,
     * and the ownership the caller verifies.
     *
     * <p>Unknown members are refused by this service's Jackson configuration, so a Commerce that grows a
     * member fails here loudly rather than being silently ignored.
     */
    public record LineContext(
            @com.fasterxml.jackson.annotation.JsonProperty("order_id")
            String orderId,

            @com.fasterxml.jackson.annotation.JsonProperty("line_id")
            String lineId,

            @com.fasterxml.jackson.annotation.JsonProperty("merchant_id")
            String merchantId,

            @com.fasterxml.jackson.annotation.JsonProperty("customer_id")
            String customerId,

            String sku,
            String category,
            int quantity,

            @com.fasterxml.jackson.annotation.JsonProperty("line_paid_amount")
            long linePaidAmount,

            @com.fasterxml.jackson.annotation.JsonProperty("refunded_amount")
            long refundedAmount,

            @com.fasterxml.jackson.annotation.JsonProperty("reserved_refund_amount")
            long reservedRefundAmount,

            String currency,

            @com.fasterxml.jackson.annotation.JsonProperty("paid_at")
            Instant paidAt,

            @com.fasterxml.jackson.annotation.JsonProperty("order_status")
            String orderStatus,

            long version,

            @com.fasterxml.jackson.annotation.JsonProperty("order_paid_amount")
            Long orderPaidAmount,

            @com.fasterxml.jackson.annotation.JsonProperty("line_refund_state")
            String lineRefundState) {

        public LineContext(
                String orderId,
                String lineId,
                String merchantId,
                String customerId,
                String sku,
                String category,
                int quantity,
                long linePaidAmount,
                long refundedAmount,
                long reservedRefundAmount,
                String currency,
                Instant paidAt,
                String orderStatus,
                long version) {
            this(
                    orderId,
                    lineId,
                    merchantId,
                    customerId,
                    sku,
                    category,
                    quantity,
                    linePaidAmount,
                    refundedAmount,
                    reservedRefundAmount,
                    currency,
                    paidAt,
                    orderStatus,
                    version,
                    null,
                    null);
        }

        /**
         * A FREE line's whole entitlement, capped by its order's remaining money.
         * Missing new facts use the conservative legacy floor; a missing slot on a new response is blocked.
         */
        public long refundableAmountMinor() {
            if (orderPaidAmount != null || lineRefundState != null) {
                if (orderPaidAmount == null
                        || !"FREE".equals(lineRefundState)
                        || orderPaidAmount < 0
                        || refundedAmount < 0
                        || reservedRefundAmount < 0
                        || refundedAmount > orderPaidAmount
                        || reservedRefundAmount > orderPaidAmount - refundedAmount) return 0;
                return Math.max(0L, Math.min(linePaidAmount, orderPaidAmount - refundedAmount - reservedRefundAmount));
            }
            return Math.max(0L, linePaidAmount - refundedAmount - reservedRefundAmount);
        }
    }

    public record PageMeta(
            @com.fasterxml.jackson.annotation.JsonProperty("next_cursor")
            String nextCursor,

            int limit) {}
}
