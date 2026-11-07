package com.resolveflow.caseservice.auth;

import com.resolveflow.caseservice.CaseDatabaseTest;
import com.resolveflow.caseservice.order.RequestPrincipalResolver.Session;
import com.resolveflow.shared.security.AuthenticatedPrincipal;
import com.resolveflow.shared.security.JwtCodec;
import com.resolveflow.shared.security.Role;
import java.time.Instant;
import java.util.Map;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.resttestclient.autoconfigure.AutoConfigureRestTestClient;
import org.springframework.http.MediaType;
import org.springframework.test.web.servlet.client.RestTestClient;

@AutoConfigureRestTestClient
class IdentityAccessApiTest extends CaseDatabaseTest {
    @Autowired
    RestTestClient rest;

    @Autowired
    JwtCodec codec;

    @Autowired
    AccountService accounts;

    static final String PATH = "/internal/v1/identity/resolve";
    final AuthenticatedPrincipal buyer =
            new AuthenticatedPrincipal("boundary-buyer", null, Role.CUSTOMER, "boundary-buyer");

    @BeforeEach
    void buyer() {
        jdbc.update("INSERT IGNORE INTO platform_buyer(buyer_id) VALUES ('boundary-buyer')");
        jdbc.update(
                "INSERT INTO identity_account(username,role,buyer_id,display_name,password_hash,identity_version) VALUES ('boundary-buyer','CUSTOMER','boundary-buyer','边界测试','unused',1) ON DUPLICATE KEY UPDATE enabled=TRUE,identity_version=1");
    }

    String user() {
        return "Bearer " + codec.issue(buyer, 1, Instant.now());
    }

    String service(String subject, String scope) {
        return "Bearer " + codec.issueServiceToken(subject, null, null, scope, Instant.now());
    }

    @Test
    void onlyCommerceDeploymentWithIdentityScopeCanResolve() {
        rest.post()
                .uri(PATH)
                .contentType(MediaType.APPLICATION_JSON)
                .body(Map.of("user_authorization", user()))
                .exchange()
                .expectStatus()
                .isUnauthorized();
        for (String token : new String[] {
            user(), service("agent-service", "identity:resolve"), service("commerce-service", "commerce:read")
        }) {
            rest.post()
                    .uri(PATH)
                    .header("Authorization", token)
                    .contentType(MediaType.APPLICATION_JSON)
                    .body(Map.of("user_authorization", user()))
                    .exchange()
                    .expectStatus()
                    .isForbidden();
        }
    }

    @Test
    void returnsOnlyCurrentPrincipalAndTrustedBindings() {
        rest.post()
                .uri(PATH)
                .header("Authorization", service("commerce-service", "identity:resolve"))
                .header("X-Merchant", "M-1002")
                .contentType(MediaType.APPLICATION_JSON)
                .body(Map.of("user_authorization", user()))
                .exchange()
                .expectStatus()
                .isOk()
                .expectBody()
                .jsonPath("$.subject")
                .isEqualTo("boundary-buyer")
                .jsonPath("$.identity_version")
                .isEqualTo(1)
                .jsonPath("$.bindings[0].merchant_id")
                .isEqualTo("M-1001")
                .jsonPath("$.bindings[0].buyer_id")
                .isEqualTo("boundary-buyer")
                .jsonPath("$.password_hash")
                .doesNotExist();
    }

    @Test
    void disableAndIdentityVersionChangesInvalidateAlreadySignedUserToken() {
        String token = user();
        jdbc.update("UPDATE identity_account SET identity_version=2 WHERE username='boundary-buyer'");
        resolve(token).expectStatus().isUnauthorized();
        jdbc.update("UPDATE identity_account SET identity_version=1,enabled=FALSE WHERE username='boundary-buyer'");
        resolve(token).expectStatus().isUnauthorized();
    }

    @Test
    void serviceTokensAndClientSpecifiedScopesCannotBecomeUserIdentity() {
        resolve(service("agent-service", "identity:resolve")).expectStatus().isUnauthorized();
        rest.post()
                .uri(PATH)
                .header("Authorization", service("commerce-service", "identity:resolve"))
                .contentType(MediaType.APPLICATION_JSON)
                .body(Map.of("user_authorization", user(), "merchant_id", "M-1002"))
                .exchange()
                .expectStatus()
                .isBadRequest();
    }

    @Test
    void shippingSnapshotRequiresCurrentOwnedAddressAndDoesNotReturnOtherProfileData() {
        var address = accounts.saveAddress(
                new Session(buyer, 1),
                null,
                new AccountService.EditAddress("边界收件人", "13800000000", "浙江省", "杭州市", "西湖区", "测试路1号", true, null));
        rest.post()
                .uri(PATH)
                .header("Authorization", service("commerce-service", "identity:resolve"))
                .contentType(MediaType.APPLICATION_JSON)
                .body(Map.of(
                        "user_authorization",
                        user(),
                        "shipping",
                        Map.of("address_id", address.address_id(), "expected_version", address.version())))
                .exchange()
                .expectStatus()
                .isOk()
                .expectBody()
                .jsonPath("$.shipping.recipient")
                .isEqualTo("边界收件人");
        rest.post()
                .uri(PATH)
                .header("Authorization", service("commerce-service", "identity:resolve"))
                .contentType(MediaType.APPLICATION_JSON)
                .body(Map.of(
                        "user_authorization",
                        user(),
                        "shipping",
                        Map.of("address_id", address.address_id(), "expected_version", address.version() + 1)))
                .exchange()
                .expectStatus()
                .isEqualTo(409);
        jdbc.update("INSERT IGNORE INTO platform_buyer(buyer_id) VALUES ('boundary-other')");
        jdbc.update(
                "INSERT INTO identity_account(username,role,buyer_id,display_name,password_hash,identity_version) VALUES ('boundary-other','CUSTOMER','boundary-other','另一买家','unused',1) ON DUPLICATE KEY UPDATE enabled=TRUE,identity_version=1");
        var other = new AuthenticatedPrincipal("boundary-other", null, Role.CUSTOMER, "boundary-other");
        rest.post()
                .uri(PATH)
                .header("Authorization", service("commerce-service", "identity:resolve"))
                .contentType(MediaType.APPLICATION_JSON)
                .body(Map.of(
                        "user_authorization",
                        "Bearer " + codec.issue(other, 1, Instant.now()),
                        "shipping",
                        Map.of("address_id", address.address_id(), "expected_version", address.version())))
                .exchange()
                .expectStatus()
                .isNotFound();
    }

    private RestTestClient.ResponseSpec resolve(String token) {
        return rest.post()
                .uri(PATH)
                .header("Authorization", service("commerce-service", "identity:resolve"))
                .contentType(MediaType.APPLICATION_JSON)
                .body(Map.of("user_authorization", token))
                .exchange();
    }
}
