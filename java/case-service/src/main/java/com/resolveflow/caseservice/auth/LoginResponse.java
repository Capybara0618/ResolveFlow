package com.resolveflow.caseservice.auth;

import com.fasterxml.jackson.annotation.JsonInclude;
import com.fasterxml.jackson.annotation.JsonProperty;
import com.resolveflow.shared.security.Role;

/**
 * The login response body (core OpenAPI {@code LoginResponse}).
 *
 * <p>Required by the schema: {@code access_token}, {@code token_type}, {@code expires_in},
 * {@code role}; customers carry a global buyer_id, and merchant staff carry merchant_id.
 * Null identity members are omitted.
 */
@JsonInclude(JsonInclude.Include.NON_NULL)
public record LoginResponse(
        @JsonProperty("access_token") String accessToken,
        @JsonProperty("token_type") String tokenType,
        @JsonProperty("expires_in") long expiresIn,
        Role role,
        @JsonProperty("merchant_id") String merchantId,
        @JsonProperty("display_name") String displayName,
        @JsonProperty("merchant_name") String merchantName,
        @JsonProperty("buyer_id") String buyerId,
        @JsonProperty("single_operator") Boolean singleOperator) {

    public static LoginResponse from(com.resolveflow.shared.security.DemoAccounts.Login login) {
        return new LoginResponse(
                login.accessToken(),
                login.tokenType(),
                login.expiresIn(),
                login.role(),
                login.merchantId(),
                null,
                null,
                login.buyerId(),
                null);
    }
}
