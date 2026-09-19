package com.resolveflow.caseservice.auth;

/**
 * The login request body (core OpenAPI {@code LoginRequest}).
 *
 * <p>{@code additionalProperties: false} is enforced by the service's Jackson configuration, so a
 * caller cannot smuggle {@code merchant_id} or {@code role} into the body: identity comes from the
 * account and from nowhere else (docs/core-contracts.md:15).
 */
public record LoginRequest(String username, String password) {

    /** Length limits come from the core OpenAPI; blank credentials are an input error, not a 401. */
    private static final int MAX_USERNAME = 120;

    private static final int MAX_PASSWORD = 200;

    public LoginRequest {
        if (username == null || username.isBlank() || username.length() > MAX_USERNAME) {
            throw new InvalidLoginRequestException("username must be 1..120 characters");
        }
        if (password == null || password.isEmpty() || password.length() > MAX_PASSWORD) {
            throw new InvalidLoginRequestException("password must be 1..200 characters");
        }
    }

    /** Raised for a body that is well-formed JSON but not a usable login request. */
    public static class InvalidLoginRequestException extends RuntimeException {

        private static final long serialVersionUID = 1L;

        public InvalidLoginRequestException(String message) {
            super(message);
        }
    }
}
