package com.resolveflow.caseservice.auth;

import static org.assertj.core.api.Assertions.*;
import static org.mockito.ArgumentMatchers.*;
import static org.mockito.Mockito.*;
import com.resolveflow.caseservice.order.RequestPrincipalResolver.Session;
import com.resolveflow.caseservice.shopping.CommerceShoppingClient;
import com.resolveflow.shared.security.AuthenticatedPrincipal;
import com.resolveflow.shared.security.Role;
import java.util.List;
import org.junit.jupiter.api.Test;
import org.mockito.ArgumentCaptor;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.core.RowMapper;
import org.springframework.transaction.PlatformTransactionManager;

class PlatformManagementPaginationTest {
    private final JdbcTemplate db = mock(JdbcTemplate.class);
    private final PlatformManagementService service = new PlatformManagementService(db, mock(PlatformTransactionManager.class), mock(CommerceShoppingClient.class));
    private final Session admin = new Session(new AuthenticatedPrincipal("admin", null, Role.PLATFORM_ADMIN, null), 1);
    private void enabled() { when(db.queryForList(contains("role='PLATFORM_ADMIN'"), eq(String.class), any(Object[].class))).thenReturn(List.of("admin")); }

    @Test
    void buyerPageUsesServerSearchAndStableAnchorBeforeLimiting() {
        enabled();
        doReturn(List.of(new PlatformManagementService.Buyer("b2","二",true,1),new PlatformManagementService.Buyer("b3","三",true,1),new PlatformManagementService.Buyer("b4","四",true,1)))
                .when(db).query(anyString(), any(RowMapper.class), any(Object[].class));
        var page = service.buyers(admin,"b1","_%",2);
        assertThat(page.items()).extracting(PlatformManagementService.Buyer::username).containsExactly("b2","b3");
        assertThat(page.next_after()).isEqualTo("b3");
        var sql = ArgumentCaptor.forClass(String.class);var args = ArgumentCaptor.forClass(Object[].class);
        verify(db).query(sql.capture(), any(RowMapper.class), args.capture());
        assertThat(sql.getValue()).contains("username>?", "ORDER BY username LIMIT ?", "LIKE ? ESCAPE '!'");
        assertThat(args.getValue()).containsExactly("b1", "%!_!%%", "%!_!%%", 3);
    }
    @Test
    void finalPageHasNoNextAndInvalidInputsAreRefused() {
        enabled();doReturn(List.of(new PlatformManagementService.Buyer("b2","二",true,1))).when(db).query(anyString(),any(RowMapper.class),any(Object[].class));
        assertThat(service.buyers(admin,null,"",2).next_after()).isNull();
        assertThatThrownBy(() -> service.buyers(admin,null,"",0)).isInstanceOf(CommerceShoppingClient.Refused.class);
        assertThatThrownBy(() -> service.merchants(admin,null,"x".repeat(101),8)).isInstanceOf(CommerceShoppingClient.Refused.class);
    }
    @Test
    void unauthorizedRolesNeverReadLists() {
        var merchant = new Session(new AuthenticatedPrincipal("m","M-1",Role.MERCHANT_ADMIN,null),1);
        assertThatThrownBy(() -> service.buyers(merchant,null,"",8)).isInstanceOf(CommerceShoppingClient.Refused.class);
        verifyNoInteractions(db);
    }
}
