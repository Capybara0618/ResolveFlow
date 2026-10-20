package com.resolveflow.shared.support;

import static org.assertj.core.api.Assertions.assertThat;

import com.resolveflow.shared.contract.ContractFixtures;
import com.resolveflow.shared.support.SupportWire.*;
import java.util.Map;
import org.junit.jupiter.api.Test;
import tools.jackson.databind.ObjectMapper;

class SupportWireTest {
    @Test
    void sharedFixturesRoundTripThroughProductionRecords() {
        var json = new ObjectMapper();
        var fixture = ContractFixtures.load("contracts/core/fixtures/support.json");
        for (var entry : Map.<String, Class<?>>of(
                        "Open",
                        Open.class,
                        "Send",
                        Send.class,
                        "Handoff",
                        Handoff.class,
                        "Reply",
                        Reply.class,
                        "Resolve",
                        Resolve.class,
                        "Conversation",
                        Conversation.class,
                        "TicketDetail",
                        TicketDetail.class)
                .entrySet()) {
            var node = fixture.get(entry.getKey());
            assertThat(json.readTree(json.writeValueAsString(json.readValue(node.toString(), entry.getValue()))))
                    .isEqualTo(node);
        }
    }
}
