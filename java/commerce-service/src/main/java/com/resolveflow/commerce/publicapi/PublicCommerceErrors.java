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

    private static ResponseEntity<ApiError> error(int status, String code, String message) {
        return ResponseEntity.status(status)
                .body(ApiError.of(
                        code, message, status >= 500, UUID.randomUUID().toString()));
    }
}
