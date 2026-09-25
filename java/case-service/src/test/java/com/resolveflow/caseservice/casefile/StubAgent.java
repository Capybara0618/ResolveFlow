package com.resolveflow.caseservice.casefile;

import com.resolveflow.shared.security.JwtCodec;
import java.util.ArrayList;
import java.util.List;
import java.util.Map;
import java.util.concurrent.atomic.AtomicInteger;
import org.springframework.web.client.RestClient;
import tools.jackson.databind.JsonNode;
import tools.jackson.databind.ObjectMapper;

/**
 * An Agent that records what Case told it.
 *
 * <p>Case's half of the dispatch protocol is "assemble the run the Agent's contract describes, and present
 * a token that says who it is for". Both of those are only checkable by looking at what went out, so this
 * stub keeps every body and the last Authorization header rather than answering a boolean.
 *
 * <p>Two failure knobs rather than one, because the caller must answer them differently: {@code failNext} is
 * an outage (retry) and {@code refuseEverySend} is the Agent saying the request itself is wrong (this
 * service's own bug). {@code failures} counts both, so a test that only cares that the loop kept trying does
 * not have to care which one it was.
 */
class StubAgent extends AgentRunClient {

    private static final ObjectMapper MAPPER = new ObjectMapper();

    /** The bodies Case handed over, in order. */
    final List<JsonNode> dispatched = new ArrayList<>();

    /** The last token presented, so a test can check the claims the Agent's verifier requires. */
    volatile String lastToken;

    /** When true the next send throws, the way an unreachable Agent does. */
    volatile boolean failNext = false;

    /** When true every send is refused, the way a wrong token or a body that disagrees with it is. */
    volatile boolean refuseEverySend = false;

    /** How many sends failed, however they failed. */
    final AtomicInteger failures = new AtomicInteger();

    StubAgent(RestClient.Builder builder, JwtCodec codec) {
        super(builder, codec, "http://agent.stub", "case-service");
    }

    @Override
    public void dispatch(String token, Map<String, Object> body) {
        lastToken = token;
        if (refuseEverySend) {
            failures.incrementAndGet();
            throw new AgentRunRejectedException("the Agent refused the run (stub)");
        }
        if (failNext) {
            failNext = false;
            failures.incrementAndGet();
            throw new AgentUnavailableException("the Agent could not be reached (stub)");
        }
        dispatched.add(MAPPER.readTree(MAPPER.writeValueAsString(body)));
    }

    /** Back to the state every test should start from. */
    void reset() {
        dispatched.clear();
        lastToken = null;
        failNext = false;
        refuseEverySend = false;
        failures.set(0);
    }
}
