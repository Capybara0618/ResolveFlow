package com.resolveflow.caseservice.casefile;

import com.resolveflow.shared.security.JwtCodec;
import java.time.Duration;
import java.time.Instant;
import org.junit.jupiter.api.Test;

/**
 * A one-off harness, not an assertion: it prints a real dispatch token so the Python Agent's verifier can
 * be pointed at a token Java actually minted.
 *
 * <p>Both sides have their own tests for this token's shape — this module asserts the claims, and the
 * Agent's {@code test_service_token.py} asserts that a token with those claims verifies. Neither of those
 * crosses the language boundary, and the boundary is where a claim name can differ by one character and
 * every test still passes. The check is run by hand; see the C06.1c record in {@code tasks/todo.md}.
 */
class DispatchTokenProbeTest {

    @Test
    void printADispatchToken() {
        JwtCodec codec = new JwtCodec("resolveflow-core-demo-identity-secret", Duration.ofHours(1));
        AgentRunClient client = new AgentRunClient(
                org.springframework.web.client.RestClient.builder(), codec, "http://unused.stub", "case-service");
        String token = client.mintDispatchToken("M-1001", "B-legacy-60865438438feefa1dfbc0ce3d07ba2cb1b09a80");
        System.out.println("DISPATCH_TOKEN=" + token);
        System.out.println("DISPATCH_TOKEN_IAT=" + Instant.now().getEpochSecond());
    }
}
