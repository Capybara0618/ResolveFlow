package com.resolveflow.caseservice.casefile;

import static org.assertj.core.api.Assertions.*;
import static org.mockito.Mockito.*;

import com.resolveflow.shared.security.AuthenticatedPrincipal;
import com.resolveflow.shared.security.Role;
import java.time.Instant;
import org.junit.jupiter.api.Test;
import tools.jackson.databind.ObjectMapper;

class ReviewerInvestigationServiceTest {
    final CaseRepository cases = mock(CaseRepository.class);
    final AgentRunBindingRepository bindings = mock(AgentRunBindingRepository.class);
    final AgentRunClient agent = mock(AgentRunClient.class);
    final ReviewerInvestigationService service = new ReviewerInvestigationService(cases, bindings, agent);
    final CaseRow row = new CaseRow(
            "case",
            "merchant",
            "customer",
            "order",
            "line",
            "问题",
            CaseStatus.PENDING_REVIEW,
            2,
            5,
            Instant.now(),
            Instant.now(),
            Instant.now());
    final AuthenticatedPrincipal staff = new AuthenticatedPrincipal("reviewer", "merchant", Role.REVIEWER, null);

    void bind() {
        when(cases.findCase("case")).thenReturn(row);
        when(bindings.find("case", 2))
                .thenReturn(new AgentRunBindingRepository.Binding(
                        "case", 2, "run", "DISPATCHED", Instant.now(), Instant.now()));
    }

    @Test
    void scopeIsCheckedBeforeAnyRemoteRead() {
        bind();
        assertThatThrownBy(() -> service.read(
                        new AuthenticatedPrincipal("customer", "merchant", Role.CUSTOMER, "customer"), "case"))
                .isInstanceOf(CaseService.ForbiddenScopeException.class);
        assertThatThrownBy(
                        () -> service.read(new AuthenticatedPrincipal("other", "other", Role.REVIEWER, null), "case"))
                .isInstanceOf(CaseReadService.CaseNotVisibleException.class);
        verifyNoInteractions(agent);
    }

    @Test
    void returnedRunMustMatchTheBindingAndOnlyApprovedFieldsReachTheView() {
        bind();
        var document = new ObjectMapper().readTree("""
                {"run_id":"wrong","case_id":"case","input_revision":2,"status":"COMPLETED",
                "internal_request":"hidden","observations":[{"observation_id":"obs","result":{"conclusion":"LOST"},"secret":"hidden"}]}
                """);
        when(agent.reviewSources(row, "run")).thenReturn(document);
        assertThat(service.read(staff, "case").availability()).isEqualTo("UNAVAILABLE");
        ((tools.jackson.databind.node.ObjectNode) document).put("run_id", "run");
        var result = service.read(staff, "case");
        assertThat(result.availability()).isEqualTo("AVAILABLE");
        assertThat(result.caseVersion()).isEqualTo(5);
        assertThat(result.investigation().toString()).contains("LOST").doesNotContain("hidden");
    }

    @Test
    void missingAndUnavailableAreDistinctAndDoNotDispatchInvestigation() {
        when(cases.findCase("case")).thenReturn(row);
        assertThat(service.read(staff, "case").availability()).isEqualTo("NOT_SCHEDULED");
        verifyNoInteractions(agent);
        bind();
        when(agent.reviewSources(row, "run")).thenThrow(new AgentRunClient.AgentUnavailableException("offline"));
        assertThat(service.read(staff, "case").availability()).isEqualTo("UNAVAILABLE");
        verify(agent).reviewSources(row, "run");
        verifyNoMoreInteractions(agent);
    }
}
