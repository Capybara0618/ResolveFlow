package com.resolveflow.caseservice.auth;

import com.fasterxml.jackson.annotation.JsonInclude;
import com.fasterxml.jackson.annotation.JsonProperty;
import com.resolveflow.shared.security.Role;

/**
 * The login response body (core OpenAPI {@code LoginResponse}).
 *
 * <p>Required by the schema: {@code access_token}, {@code token_type}, {@code expires_in},
 * {@code role}, {@code merchant_id}; {@code customer_id} is present exactly for a customer-scoped
 * account and is omitted otherwise, so "not a customer" has one representation instead of two.
 */
@JsonInclude(JsonInclude.Include.NON_NULL)
public record LoginResponse(
        @JsonProperty("access_token") String accessToken,
        @JsonProperty("token_type") String tokenType,
        @JsonProperty("expires_in") long expiresIn,
        Role role,
        @JsonProperty("merchant_id") String merchantId,
        @JsonProperty("customer_id") String customerId) {

    public static LoginResponse from(com.resolveflow.shared.security.DemoAccounts.Login login) {
        return new LoginResponse(
                login.accessToken(),
                login.tokenType(),
                login.expiresIn(),
                login.role(),
                login.merchantId(),
                login.customerId());
    }
}
