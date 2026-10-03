package com.resolveflow.caseservice.casefile;

import static org.assertj.core.api.Assertions.*;

import com.resolveflow.caseservice.CaseDatabaseTest;
import com.resolveflow.caseservice.auth.PersistentAccounts;
import com.resolveflow.caseservice.auth.StaffAdminService;
import com.resolveflow.caseservice.order.RequestPrincipalResolver;
import com.resolveflow.shared.security.AuthenticatedPrincipal;
import com.resolveflow.shared.security.DemoAccounts;
import com.resolveflow.shared.security.Role;
import java.time.Instant;
import java.util.List;
import java.util.UUID;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.context.annotation.Import;

@Import(CaseApiTest.StubCommerceConfiguration.class)
class MerchantSingleAccountTest extends CaseDatabaseTest {
    @Autowired
    CaseService service;

    @Autowired
    CaseCollaborationService collaboration;

    @Autowired
    PersistentAccounts accounts;

    @Autowired
    StaffAdminService people;

    @Autowired
    StubCommerce commerce;

    private final AuthenticatedPrincipal merchant =
            new AuthenticatedPrincipal("demo-admin", "M-1001", Role.MERCHANT_ADMIN, null);

    @BeforeEach
    void setup() {
        deleteAllCaseData(jdbc);
        jdbc.update("UPDATE identity_merchant SET single_operator=TRUE WHERE merchant_id='M-1001'");
        commerce.lineVisible = true;
    }

    @AfterEach
    void cleanup() {
        deleteAllCaseData(jdbc);
        jdbc.update("UPDATE identity_merchant SET single_operator=FALSE WHERE merchant_id='M-1001'");
        jdbc.update("UPDATE identity_merchant SET enabled=TRUE WHERE merchant_id='M-1001'");
        jdbc.update("UPDATE identity_account SET enabled=TRUE WHERE username='demo-admin'");
        jdbc.update("DELETE FROM identity_account WHERE username='solo-extra'");
    }

    private String create() {
        return service.create(
                        new AuthenticatedPrincipal("demo-customer", "M-1001", Role.CUSTOMER, "C-2002"),
                        UUID.randomUUID().toString(),
                        new CaseCreateRequest("7001", "合成未发货退款申请", List.of("REFUND")))
                .body()
                .caseId();
    }

    @Test
    void newCaseIsAssignedInsideCreationWithoutHumanClaim() {
        String id = create();
        var view = collaboration.read(merchant, id);
        assertThat(view.isOwner()).isTrue();
        assertThat(view.version()).isEqualTo(1);
        assertThat(view.allowedActions()).isEmpty();
        assertThat(view.history()).singleElement().satisfies(e -> {
            assertThat(e.action()).isEqualTo("AUTO_ASSIGN");
            assertThat(e.actorUsername()).isEqualTo("SYSTEM");
        });
        var row =
                collaboration.prepareWrite(merchant, id, new CaseCollaborationService.WritePermit(0, "\"1\"", "\"1\""));
        assertThat(row.inputRevision()).isEqualTo(1);
        assertThatThrownBy(() -> collaboration.prepareWrite(
                        merchant, id, new CaseCollaborationService.WritePermit(0, "\"1\"", "\"0\"")))
                .isInstanceOf(CaseStateConflictException.class);
    }

    @Test
    void missingOrMultipleMerchantAccountRollsBackCaseAndRunBinding() {
        jdbc.update("UPDATE identity_account SET enabled=FALSE WHERE username='demo-admin'");
        assertThatThrownBy(this::create).isInstanceOf(RuntimeException.class);
        assertThat(jdbc.queryForObject("SELECT COUNT(*) FROM aftersale_case", Integer.class))
                .isZero();
        jdbc.update("UPDATE identity_account SET enabled=TRUE WHERE username='demo-admin'");
        jdbc.update(
                "INSERT INTO identity_account(username,merchant_id,role,display_name,password_hash) SELECT 'solo-extra',merchant_id,role,'额外商家',password_hash FROM identity_account WHERE username='demo-admin'");
        assertThatThrownBy(this::create).isInstanceOf(RuntimeException.class);
        assertThat(jdbc.queryForObject("SELECT COUNT(*) FROM agent_binding", Integer.class))
                .isZero();
    }

    @Test
    void personnelAndManualAssignmentAreNotAvailableInSingleAccountMode() {
        String id = create();
        assertThatThrownBy(() -> collaboration.act(
                        merchant, 0, id, "\"1\"", new CaseCollaborationService.Action("RELEASE", null, "手工释放")))
                .isInstanceOf(CaseService.ForbiddenScopeException.class);
        var session = new RequestPrincipalResolver.Session(merchant, 0);
        assertThatThrownBy(() -> people.create(
                        session, new StaffAdminService.Create("solo-extra", "额外人员", "REVIEWER", "123456", "测试")))
                .isInstanceOf(CaseService.ForbiddenScopeException.class);
        assertThat(collaboration.read(merchant, id).isOwner()).isTrue();
    }

    @Test
    void oldReviewerCannotLoginButMerchantAdvertisesUnifiedWorkspace() {
        assertThatThrownBy(() -> accounts.login("demo-reviewer", "demo-pass-1003", Instant.now()))
                .isInstanceOf(DemoAccounts.CredentialsRejectedException.class);
        assertThat(accounts.login("demo-admin", "demo-pass-1100", Instant.now()).singleOperator())
                .isTrue();
    }

    @Test
    void disabledMerchantCannotGetAWorkflowWithNoOwner() {
        jdbc.update("UPDATE identity_merchant SET enabled=FALSE WHERE merchant_id='M-1001'");
        assertThatThrownBy(this::create).isInstanceOf(CaseService.ForbiddenScopeException.class);
        assertThat(jdbc.queryForObject("SELECT COUNT(*) FROM aftersale_case", Integer.class))
                .isZero();
    }
}
