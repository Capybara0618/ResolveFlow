package com.resolveflow.caseservice.casefile;

import com.resolveflow.shared.security.JwtCodec;
import java.time.Instant;
import java.util.Map;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.http.HttpHeaders;
import org.springframework.http.MediaType;
import org.springframework.stereotype.Component;
import org.springframework.web.client.RestClient;

/**
 * Case's relationship with the Agent, in one place.
 *
 * <p>Follows {@code CommerceOrderLineClient}, and for the same two reasons: the token is minted here rather
 * than by its caller (a dispatch that could name its own subject could dispatch as somebody else), and the
 * base URL is configuration rather than a value read from a request.
 *
 * <p><b>What this client does not do is decide whether the run was accepted.</b> It returns the Agent's
 * answer and lets {@link AgentRunDispatch} interpret it, because "accepted" is a fact about the binding row
 * and not about one HTTP exchange.
 */
@Component
public class AgentRunClient {

    /**
     * Raised when the Agent could not be reached or refused the request in a way that might change.
     *
     * <p>An outage and a 5xx are the same answer to the caller: leave the binding PENDING and try again.
     * A 4xx is not this exception — see {@link AgentRunRejectedException}.
     */
    public static class AgentUnavailableException extends RuntimeException {

        private static final long serialVersionUID = 1L;

        public AgentUnavailableException(String message) {
            super(message);
        }

        public AgentUnavailableException(String message, Throwable cause) {
            super(message, cause);
        }
    }

    /**
     * Raised when the Agent refused the run itself (a 4xx).
     *
     * <p>Separate from the outage because the two need opposite answers. A 401/403 means this service's
     * token is wrong, and a 422 means the body disagrees with the token or the contract. Retrying either
     * forever would leave a binding that never dispatches, looking exactly like an Agent that is down —
     * so the dispatch reports it as a failure with the reason attached, and the row stays visible instead
     * of being quietly marked delivered.
     */
    public static class AgentRunRejectedException extends RuntimeException {

        private static final long serialVersionUID = 1L;

        public AgentRunRejectedException(String message) {
            super(message);
        }
    }

    private final RestClient rest;
    private final JwtCodec codec;
    private final String serviceName;

    public AgentRunClient(
            RestClient.Builder builder,
            JwtCodec jwtCodec,
            @Value("${resolveflow.agent.base-url}") String baseUrl,
            @Value("${resolveflow.identity.service-name:case-service}") String serviceName) {
        this.rest = builder.baseUrl(baseUrl).build();
        this.codec = jwtCodec;
        this.serviceName = serviceName;
    }

    /**
     * Hand one run to the Agent, or say why it was not accepted.
     *
     * <p>The token is minted per attempt rather than held: an outage outlives any reasonable token lifetime,
     * and a token minted once and retried later would come back 401 — which reads as a permissions bug and
     * would send an operator looking at the wrong thing.
     */
    public void dispatch(String token, Map<String, Object> body) {
        try {
            rest.post()
                    .uri("/internal/v1/runs")
                    .header(HttpHeaders.AUTHORIZATION, "Bearer " + token)
                    .contentType(MediaType.APPLICATION_JSON)
                    .accept(MediaType.APPLICATION_JSON)
                    .body(body)
                    .retrieve()
                    // The Agent answers 202 only after the row is committed (contracts/core/openapi-agent.yaml:89).
                    // Anything else is either an outage or a refusal, and the two are told apart by status.
                    .onStatus(status -> status.is4xxClientError(), (request, response) -> {
                        throw new AgentRunRejectedException(
                                "the Agent refused the run with " + response.getStatusCode());
                    })
                    .onStatus(status -> status.is5xxServerError(), (request, response) -> {
                        throw new AgentUnavailableException(
                                "the Agent could not accept the run: " + response.getStatusCode());
                    })
                    .toBodilessEntity();
        } catch (AgentRunRejectedException error) {
            throw error;
        } catch (AgentUnavailableException error) {
            throw error;
        } catch (RuntimeException error) {
            // A connection that never opened, a timeout, an unreadable answer: all of them mean "not
            // accepted yet", which is a retry rather than a lost run.
            throw new AgentUnavailableException("the Agent could not be reached", error);
        }
    }

    /** The service token a dispatch presents. Minted per attempt by {@link #dispatch}. */
    public String mintDispatchToken(String merchantId, String customerId) {
        return codec.issueServiceToken(serviceName, merchantId, customerId, "run:dispatch", Instant.now());
    }
}
