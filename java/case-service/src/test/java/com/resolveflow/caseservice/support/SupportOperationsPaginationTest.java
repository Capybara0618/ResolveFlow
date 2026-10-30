package com.resolveflow.caseservice.support;

import static org.assertj.core.api.Assertions.*;
import static org.mockito.ArgumentMatchers.*;
import static org.mockito.Mockito.*;

import com.resolveflow.caseservice.order.RequestPrincipalResolver;
import com.resolveflow.shared.security.AuthenticatedPrincipal;
import com.resolveflow.shared.security.Role;
import java.sql.Timestamp;
import java.time.Instant;
import java.util.List;
import java.util.Map;
import org.junit.jupiter.api.Test;
import org.mockito.ArgumentCaptor;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.core.RowMapper;
import tools.jackson.databind.ObjectMapper;

class SupportOperationsPaginationTest {
    private final JdbcTemplate db = mock(JdbcTemplate.class);
    private final RequestPrincipalResolver principals = mock(RequestPrincipalResolver.class);
    private final SupportOperationsController controller =
            new SupportOperationsController(db, principals, new ObjectMapper());

    private void admin() {
        when(principals.session("admin"))
                .thenReturn(new RequestPrincipalResolver.Session(
                        new AuthenticatedPrincipal("admin", null, Role.PLATFORM_ADMIN, null), 1));
    }

    private SupportOperationsController.Run run(String id) {
        return new SupportOperationsController.Run(
                id, "M-1", "FAILED", null, null, Instant.parse("2026-10-30T00:00:00Z"), null, null, null, Map.of());
    }

    @Test
    void usesBothTimeAndIdAtTheBoundaryAndFiltersBeforeTheLimit() {
        admin();
        String anchor = "00000000-0000-4000-8000-000000000003";
        var at = Timestamp.from(Instant.parse("2026-10-30T00:00:00Z"));
        when(db.queryForList(anyString(), eq(Timestamp.class), any(Object[].class)))
                .thenReturn(List.of(at));
        doReturn(List.of(run("b"), run("a"))).when(db).query(anyString(), any(RowMapper.class), any(Object[].class));
        var page = controller.list("admin", anchor, 1, "_%", "FAILED");
        assertThat(page.items())
                .extracting(SupportOperationsController.Run::run_id)
                .containsExactly("b");
        assertThat(page.next_before()).isEqualTo("b");
        var sql = ArgumentCaptor.forClass(String.class);
        var args = ArgumentCaptor.forClass(Object[].class);
        verify(db).query(sql.capture(), any(RowMapper.class), args.capture());
        assertThat(sql.getValue())
                .contains(
                        "t.created_at<? OR (t.created_at=? AND t.run_id<?)",
                        "AND t.status=?",
                        "ORDER BY t.created_at DESC,t.run_id DESC LIMIT ?");
        assertThat(args.getValue()).containsExactly(at, at, anchor, "%!_!%%", "%!_!%%", "FAILED", 2);
    }

    @Test
    void rejectsInvalidCursorsAndLimitsWithoutQueryingData() {
        admin();
        assertThatThrownBy(() -> controller.list("admin", "bad", 8, "", "")).isInstanceOf(SupportService.Refused.class);
        assertThatThrownBy(() -> controller.list("admin", null, 51, "", "")).isInstanceOf(SupportService.Refused.class);
        verifyNoInteractions(db);
    }
}
