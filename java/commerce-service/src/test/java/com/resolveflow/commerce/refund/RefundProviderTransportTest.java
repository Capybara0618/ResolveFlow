package com.resolveflow.commerce.refund;

import static org.assertj.core.api.Assertions.assertThat;

import com.sun.net.httpserver.HttpServer;
import java.net.InetSocketAddress;
import java.util.UUID;
import org.junit.jupiter.api.Test;
import org.springframework.http.client.SimpleClientHttpRequestFactory;
import org.springframework.web.client.RestClient;
import tools.jackson.databind.ObjectMapper;

class RefundProviderTransportTest {
    @Test
    void socketClosedAfterReceivingRequestIsUnknownAndRetainsOriginalQueryKey() throws Exception {
        var provider = HttpServer.create(new InetSocketAddress("127.0.0.1", 0), 0);
        provider.createContext("/provider/v1/refunds", exchange -> {
            exchange.getRequestBody().readAllBytes();
            exchange.close();
        });
        provider.start();
        try {
            var requests = new SimpleClientHttpRequestFactory();
            requests.setConnectTimeout(1000);
            requests.setReadTimeout(1000);
            var client = new RefundProviderClient(
                    RestClient.builder().requestFactory(requests),
                    new ObjectMapper(),
                    "http://127.0.0.1:" + provider.getAddress().getPort());
            String operation = UUID.randomUUID().toString();
            assertThat(client.requestRefund(operation, "synthetic-lost-response", 2599, "CNY")
                            .isUnknown())
                    .isTrue();
            var query = client.queryRefund(operation);
            assertThat(query.isUnknown()).isTrue();
            assertThat(query.operationId()).isEqualTo(operation);
        } finally {
            provider.stop(0);
        }
    }
}
