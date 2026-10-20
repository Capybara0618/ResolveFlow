package com.resolveflow.caseservice.support;

import java.time.Duration;
import java.util.Map;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.http.client.SimpleClientHttpRequestFactory;
import org.springframework.stereotype.Component;
import org.springframework.web.client.RestClient;
import tools.jackson.databind.JsonNode;

@Component
public class SupportAgentClient {
    private final RestClient client;

    public SupportAgentClient(RestClient.Builder builder, @Value("${resolveflow.agent.base-url}") String base) {
        var transport = new SimpleClientHttpRequestFactory();
        transport.setConnectTimeout(Duration.ofSeconds(3));
        transport.setReadTimeout(Duration.ofSeconds(130));
        client = builder.clone().baseUrl(base).requestFactory(transport).build();
    }

    public JsonNode execute(String token, Map<String, Object> body) {
        return client.post()
                .uri("/internal/v1/support-runs")
                .header("Authorization", "Bearer " + token)
                .contentType(org.springframework.http.MediaType.APPLICATION_JSON)
                .body(body)
                .retrieve()
                .body(JsonNode.class);
    }
}
