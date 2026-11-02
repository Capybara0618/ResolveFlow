package com.resolveflow.commerce.publicapi;

import com.resolveflow.commerce.catalog.ShoppingService;
import com.resolveflow.commerce.security.IdentityAccessClient;
import com.resolveflow.shared.error.ApiError;
import java.util.UUID;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.*;

@RestControllerAdvice(basePackages = "com.resolveflow.commerce.publicapi")
public class PublicCommerceErrors {
    @ExceptionHandler(ShoppingService.Refused.class)
    public ResponseEntity<ApiError> refused(ShoppingService.Refused e) {
        return error(e.status, e.code, e.getMessage());
    }

    @ExceptionHandler(IdentityAccessClient.Refused.class)
    public ResponseEntity<ApiError> identity(IdentityAccessClient.Refused e) {
        return error(e.status, e.code, e.getMessage());
    }

    @ExceptionHandler(ReviewWriteLimiter.WriteLimited.class)
    public ResponseEntity<ApiError> limited() {
        return ResponseEntity.status(429)
                .header("Retry-After", "60")
                .body(ApiError.of(
                        "RATE_LIMITED", "评价操作较频繁，请稍后再试", true, UUID.randomUUID().toString()));
    }

    @ExceptionHandler(ReviewWriteLimiter.WriteUnavailable.class)
    public ResponseEntity<ApiError> unavailable() {
        return ResponseEntity.status(503)
                .header("Retry-After", "1")
                .body(ApiError.of(
                        "SERVICE_UNAVAILABLE",
                        "评价暂时无法保存，请稍后确认原操作结果",
                        true,
                        UUID.randomUUID().toString()));
    }

    private static ResponseEntity<ApiError> error(int status, String code, String message) {
        return ResponseEntity.status(status)
                .body(ApiError.of(
                        code, message, status >= 500, UUID.randomUUID().toString()));
    }
}
