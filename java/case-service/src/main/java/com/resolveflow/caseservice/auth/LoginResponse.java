package com.resolveflow.caseservice.auth;

import com.fasterxml.jackson.annotation.JsonInclude;
import com.fasterxml.jackson.annotation.JsonProperty;
import com.resolveflow.shared.security.Role;

/**
 * The login response body (core OpenAPI {@code LoginResponse}).
 *
 * <p>Required by the schema: {@code access_token}, {@code token_type}, {@code expires_in},
 * {@code role}; the exclusive identity is either merchant/customer for legacy customers,
 * merchant for staff, or buyer_id for platform customers. Null identity members are omitted.
 */
@JsonInclude(JsonInclude.Include.NON_NULL)
public record LoginResponse(
        @JsonProperty("access_token") String accessToken,
        @JsonProperty("token_type") String tokenType,
        @JsonProperty("expires_in") long expiresIn,
        Role role,
        @JsonProperty("merchant_id") String merchantId,
        @JsonProperty("customer_id") String customerId,
        @JsonProperty("display_name") String displayName,
        @JsonProperty("merchant_name") String merchantName,
        @JsonProperty("buyer_id") String buyerId) {

    public LoginResponse(
            String accessToken,
            String tokenType,
            long expiresIn,
            Role role,
            String merchantId,
            String customerId,
            String displayName,
            String merchantName) {
        this(accessToken, tokenType, expiresIn, role, merchantId, customerId, displayName, merchantName, null);
    }

    public static LoginResponse from(com.resolveflow.shared.security.DemoAccounts.Login login) {
        return new LoginResponse(
                login.accessToken(),
                login.tokenType(),
                login.expiresIn(),
                login.role(),
                login.merchantId(),
                login.customerId(),
                null,
                null);
    }
}
