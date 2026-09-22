package com.resolveflow.commerce.refund;

import org.springframework.beans.factory.annotation.Value;
import org.springframework.http.MediaType;
import org.springframework.stereotype.Component;
import org.springframework.web.client.ResourceAccessException;
import org.springframework.web.client.RestClient;
import tools.jackson.databind.JsonNode;
import tools.jackson.databind.ObjectMapper;
import tools.jackson.databind.node.ObjectNode;

/**
 * The outside world, over HTTP (fixtures/provider/README.md).
 *
 * <p>Three answers matter and they are three different things:
 *
 * <ul>
 *   <li>a state — {@code SUCCEEDED}, {@code FAILED}, or {@code UNKNOWN} — which is what the provider
 *       believes about the money;
 *   <li>{@code responded=false}, which means this call did not get an answer even though the provider may
 *       have settled. A lost response is the case the whole idempotent-retry design exists for;
 *   <li>404, which means "I have nothing for this key". It is **not** a failure: a provider inside its
 *       delayed-visibility window answers 404 while it already holds the money, so treating it as a
 *       determined failure would release a reservation for money that is gone
 *       (docs/domain-model.md:51).
 * </ul>
 *
 * <p>A transport error (connection refused, read timeout) becomes {@code UNKNOWN} rather than an exception,
 * because that is exactly what "the network did not tell me" means
 * (docs/domain-model.md:51 — 网络超时=UNKNOWN而非失败). Raising it would push the decision to a caller that
 * has less information; the money path has to keep the reservation and ask again.
 */
@Component
public class RefundProviderClient {

    /** The provider's answer, in this service's own vocabulary. */
    public record ProviderAnswer(
            String operationId, String state, String providerRef, String reasonCode, boolean responded, String detail) {

        /**
         * True only when an outcome actually arrived.
         *
         * <p>{@code responded=false} means this call did not receive a reply even though the provider may
         * have settled. Treating that as a confirmed success would settle money the caller never heard about
         * — and worse, it would make the retry pointless, because the operation would already look finished.
         * A lost response is therefore an {@code UNKNOWN} with a story attached
         * (fixtures/provider/README.md §1).
         */
        public boolean isRefunded() {
            return responded && "SUCCEEDED".equals(state);
        }

        public boolean isRefused() {
            return responded && "FAILED".equals(state);
        }

        public boolean isUnknown() {
            return !responded || "UNKNOWN".equals(state);
        }
    }

    private final RestClient rest;
    private final ObjectMapper mapper;

    public RefundProviderClient(
            RestClient.Builder builder,
            ObjectMapper mapper,
            @Value("${resolveflow.provider.base-url}") String baseUrl) {
        this.rest = builder.baseUrl(baseUrl).build();
        this.mapper = mapper;
    }

    /**
     * Ask the provider for one refund, using the operation id as the idempotency key.
     *
     * <p>The key is the caller's, not the provider's: a retry has to carry the same one or the provider
     * cannot tell a retry from a new payment.
     */
    public ProviderAnswer requestRefund(String operationId, String lineId, long amountMinor, String currency) {
        ObjectNode body = mapper.createObjectNode();
        body.put("operation_id", operationId);
        body.put("line_id", lineId);
        body.put("amount_minor", amountMinor);
        body.put("currency", currency);
        return call(() -> rest.post()
                .uri("/provider/v1/refunds")
                .contentType(MediaType.APPLICATION_JSON)
                .body(body.toString())
                .retrieve()
                .body(String.class));
    }

    /**
     * Read what the provider believes.
     *
     * <p>A 404 comes back as {@code NOT_FOUND} rather than as an error or as {@code FAILED}: "the provider
     * has nothing" and "the provider refused" are different sentences, and only one of them releases money.
     */
    public ProviderAnswer queryRefund(String operationId) {
        try {
            String body = rest.get()
                    .uri("/provider/v1/refunds/{key}", operationId)
                    .retrieve()
                    .onStatus(status -> status.value() == 404, (request, response) -> {
                        throw new ProviderNotFound(operationId);
                    })
                    .body(String.class);
            return parse(body, operationId);
        } catch (ProviderNotFound notFound) {
            return new ProviderAnswer(
                    operationId, "NOT_FOUND", null, null, true, "the provider has nothing for this key");
        } catch (ResourceAccessException unreachable) {
            return unknown(operationId, "the provider could not be reached: " + unreachable.getMessage());
        }
    }

    private ProviderAnswer call(java.util.function.Supplier<String> call) {
        try {
            return parse(call.get(), null);
        } catch (ResourceAccessException unreachable) {
            // No answer arrived. The provider may still have taken the money, so this is UNKNOWN: keeping
            // the reservation is the only safe reading of "I do not know".
            return unknown(null, "the provider could not be reached: " + unreachable.getMessage());
        }
    }

    private ProviderAnswer parse(String body, String fallbackOperationId) {
        if (body == null || body.isBlank()) {
            return unknown(fallbackOperationId, "the provider answered with an empty body");
        }
        JsonNode node = mapper.readTree(body);
        String state = node.path("state").asString("UNKNOWN");
        String operationId = node.path("operation_id").asString(fallbackOperationId);
        boolean responded = node.path("responded").asBoolean(true);
        String reason = node.hasNonNull("reason_code") ? node.get("reason_code").stringValue() : null;
        String ref = node.hasNonNull("provider_ref") ? node.get("provider_ref").stringValue() : null;
        return new ProviderAnswer(operationId, state, ref, reason, responded, null);
    }

    private static ProviderAnswer unknown(String operationId, String detail) {
        return new ProviderAnswer(operationId, "UNKNOWN", null, "PROVIDER_UNREACHABLE", false, detail);
    }

    /** Raised internally to turn the provider's 404 into a {@code NOT_FOUND} answer. */
    static final class ProviderNotFound extends RuntimeException {

        private static final long serialVersionUID = 1L;

        ProviderNotFound(String operationId) {
            super(operationId);
        }
    }
}
