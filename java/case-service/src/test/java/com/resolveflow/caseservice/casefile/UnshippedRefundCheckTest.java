package com.resolveflow.caseservice.casefile;

import static org.assertj.core.api.Assertions.*;
import static org.mockito.Mockito.*;

import com.resolveflow.caseservice.order.CommerceOrderLineClient.CommerceUnavailableException;
import com.resolveflow.caseservice.shopping.CommerceShoppingClient;
import com.resolveflow.shared.shopping.FulfillmentWire.*;
import java.time.Instant;
import java.util.List;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.ValueSource;
import tools.jackson.databind.ObjectMapper;

class UnshippedRefundCheckTest {
    private static final Instant NOW = Instant.parse("2026-10-03T08:00:00Z");
    private final CommerceShoppingClient commerce = mock(CommerceShoppingClient.class);
    private final ProposalRepository proposals = mock(ProposalRepository.class);
    private final UnshippedRefundCheck check = new UnshippedRefundCheck(commerce, proposals, new ObjectMapper());
    private final CaseRow row = new CaseRow(
            "case", "M-1001", "C-1", "order", "line", "尚未发货", CaseStatus.PENDING_REVIEW, 1, 2, NOW, NOW, NOW);
    private final List<PolicyCitation> refs =
            List.of(new PolicyCitation("bundle", "2026.10", "R-UNSHIPPED-001", "chunk", "a".repeat(64)));

    private Fulfillment snapshot(String status, Long version, String lineId, List<Event> events) {
        return new Fulfillment(
                "order", status, true, version, NOW, List.of(new Tracking(lineId, status, "UNKNOWN", version, events)));
    }

    private List<Event> paid() {
        return List.of(new Event("ORDER_PAID", NOW, 1));
    }

    @Test
    void explicitCurrentFactAndTrustedOwnershipPass() {
        when(commerce.fulfillment("order", "M-1001", "C-1")).thenReturn(snapshot("NOT_SHIPPED", 1L, "line", paid()));
        assertThat(check.failure(row, refs)).isNull();
        verify(commerce).fulfillment("order", "M-1001", "C-1");
    }

    @ParameterizedTest
    @ValueSource(strings = {"IN_TRANSIT", "DELIVERED", "LOST", "UNKNOWN"})
    void allOtherStatesCannotUseTheUnshippedRule(String status) {
        when(commerce.fulfillment("order", "M-1001", "C-1")).thenReturn(snapshot(status, 2L, "line", paid()));
        assertThat(check.failure(row, refs)).isNotNull();
    }

    @Test
    void missingVersionLineOrPaidEventAreNotUnshippedProof() {
        for (var snapshot : List.of(
                snapshot("NOT_SHIPPED", null, "line", paid()),
                snapshot("NOT_SHIPPED", 1L, "foreign", paid()),
                snapshot("NOT_SHIPPED", 1L, "line", List.of()),
                snapshot("NOT_SHIPPED", 1L, "line", List.of(new Event("SIMULATED_SHIPPED", NOW, 1))))) {
            when(commerce.fulfillment("order", "M-1001", "C-1")).thenReturn(snapshot);
            assertThat(check.failure(row, refs)).isNotNull();
        }
    }

    @Test
    void missingLogisticsRefusesAndAnOutagePropagates() {
        when(commerce.fulfillment("order", "M-1001", "C-1"))
                .thenThrow(new CommerceShoppingClient.Refused(404, "NOT_FOUND", "missing"));
        assertThat(check.failure(row, refs)).contains("缺失");
        doThrow(new CommerceUnavailableException("offline", null))
                .when(commerce)
                .fulfillment("order", "M-1001", "C-1");
        assertThatThrownBy(() -> check.failure(row, refs)).isInstanceOf(CommerceUnavailableException.class);
    }

    @Test
    void legacyCitationsDoNotAddAShoppingDependency() {
        assertThat(check.failure(
                        row, List.of(new PolicyCitation("old", "2026.09", "R-LOST-001", "chunk", "a".repeat(64)))))
                .isNull();
        verifyNoInteractions(commerce);
    }
}
