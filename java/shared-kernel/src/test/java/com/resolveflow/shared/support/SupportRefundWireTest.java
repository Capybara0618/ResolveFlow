package com.resolveflow.shared.support;

import static org.assertj.core.api.Assertions.assertThat;

import com.resolveflow.shared.contract.ContractFixtures;
import com.resolveflow.shared.support.SupportRefundWire.*;
import java.util.Map;
import org.junit.jupiter.api.Test;
import tools.jackson.databind.ObjectMapper;

class SupportRefundWireTest {
    @Test
    void customerRefundFixturesRoundTripThroughProductionRecords() {
        var json = new ObjectMapper();
        var fixture = ContractFixtures.load("contracts/core/fixtures/support-refund.json");
        for (var entry : Map.<String, Class<?>>of(
                        "Prepare", Prepare.class, "Edit", Edit.class, "Revision", Revision.class, "Draft", Draft.class)
                .entrySet()) {
            var node = fixture.get(entry.getKey());
            assertThat(json.readTree(json.writeValueAsString(json.readValue(node.toString(), entry.getValue()))))
                    .isEqualTo(node);
        }
    }
}
