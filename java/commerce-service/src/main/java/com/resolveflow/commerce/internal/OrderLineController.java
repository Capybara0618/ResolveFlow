package com.resolveflow.commerce.internal;

import com.fasterxml.jackson.annotation.JsonInclude;
import com.fasterxml.jackson.annotation.JsonProperty;
import com.resolveflow.commerce.order.OrderLineReadService;
import com.resolveflow.commerce.order.OrderLineRow;
import com.resolveflow.shared.security.JwtCodec;
import java.time.Duration;
import java.time.Instant;
import java.util.List;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

/**
 * {@code GET /internal/v1/order-lines}: the listing Case's public order view is built from.
 *
 * <p>Added in C01.2 because the authority table's Case row says the order view calls Commerce
 * internally (docs/core-contracts.md:26) while no listing route existed; the schema shapes are
 * byte-identical to Case's public ones and a contract test keeps them that way.
 *
 * <p>The response members are snake_case exactly as the core OpenAPI declares them, including
 * {@code line_paid_amount} and {@code next_cursor}; {@code paid_at} is a UTC instant with a trailing
 * Z (docs/core-contracts.md:17), which is why the driver is pinned to UTC rather than left on the
 * JVM default zone.
 */
@RestController
@RequestMapping("/internal/v1/order-lines")
public class OrderLineController {

    private final OrderLineReadService service;

    public OrderLineController(OrderLineReadService service) {
        this.service = service;
    }

    @GetMapping
    public ResponseEntity<OrderLinePageResponse> list(
            @RequestParam("merchant_id") String merchantId,
            @RequestParam(name = "customer_id", required = false) String customerId,
            @RequestParam(name = "cursor", required = false) String cursor,
            @RequestParam(name = "limit", required = false) Integer limit) {
        OrderLineReadService.Page page = service.list(merchantId, customerId, cursor, limit);
        return ResponseEntity.ok(new OrderLinePageResponse(
                page.items().stream().map(OrderLineSummaryResponse::from).toList(),
                new PageMetaResponse(page.nextCursor(), page.limit())));
    }

    /** One row of the page; the owning merchant/customer are not echoed back to the caller. */
    @JsonInclude(JsonInclude.Include.NON_NULL)
    public record OrderLineSummaryResponse(
            @JsonProperty("order_id") String orderId,
            @JsonProperty("line_id") String lineId,
            String sku,
            String category,
            int quantity,
            @JsonProperty("line_paid_amount") long linePaidAmount,
            String currency,
            @JsonProperty("paid_at") Instant paidAt,
            String status,
            long version) {

        static OrderLineSummaryResponse from(OrderLineRow row) {
            return new OrderLineSummaryResponse(
                    row.orderId(),
                    row.lineId(),
                    row.sku(),
                    row.category(),
                    row.quantity(),
                    row.linePaidAmount(),
                    row.currency(),
                    row.paidAt(),
                    row.status(),
                    row.version());
        }
    }

    /** {@code next_cursor} is absent exactly when there is no next page. */
    @JsonInclude(JsonInclude.Include.NON_NULL)
    public record PageMetaResponse(
            @JsonProperty("next_cursor") String nextCursor, int limit) {}

    public record OrderLinePageResponse(List<OrderLineSummaryResponse> items, PageMetaResponse page) {}

    /**
     * The internal surface's own token codec.
     *
     * <p>Same demonstration secret as case-service, because the two have to agree for a token to
     * verify at all; the separation that matters is the audience, which the filter checks. A real
     * deployment supplies the secret from its environment and would rotate it per environment.
     */
    @Configuration
    public static class InternalSecurityConfiguration {

        @Bean
        JwtCodec serviceTokenCodec(
                @Value("${resolveflow.identity.jwt.secret}") String secret,
                @Value("${resolveflow.identity.jwt.ttl-seconds:3600}") long ttlSeconds) {
            return new JwtCodec(secret, Duration.ofSeconds(ttlSeconds));
        }
    }
}
