package com.resolveflow.caseservice.auth;

import com.resolveflow.caseservice.auth.AccountService.*;
import com.resolveflow.caseservice.order.RequestPrincipalResolver;
import com.resolveflow.caseservice.shopping.CommerceShoppingClient.Refused;
import com.resolveflow.shared.error.ApiError;
import java.io.IOException;
import java.util.List;
import java.util.UUID;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.*;
import org.springframework.web.multipart.MultipartFile;

@RestController
@RequestMapping("/api/v1/account")
public class AccountController {
    private final AccountService service;
    private final RequestPrincipalResolver principals;

    public AccountController(AccountService service, RequestPrincipalResolver principals) {
        this.service = service;
        this.principals = principals;
    }

    public record Version(Long expected_version) {}

    public record Addresses(List<Address> items) {}

    @GetMapping("/profile")
    public Profile profile(@RequestHeader(name = "Authorization", required = false) String auth) {
        return service.profile(principals.session(auth));
    }

    @PostMapping("/profile")
    public Profile edit(
            @RequestHeader(name = "Authorization", required = false) String auth, @RequestBody EditProfile body) {
        return service.edit(principals.session(auth), body);
    }

    @PostMapping(value = "/avatar", consumes = "multipart/form-data")
    public Profile upload(
            @RequestHeader(name = "Authorization", required = false) String auth,
            @RequestParam Long expected_version,
            @RequestParam MultipartFile file)
            throws IOException {
        var session = principals.session(auth);
        if (file.getSize() > 2 * 1024 * 1024) throw new Refused(400, "INVALID_IMAGE", "请选择2MB以内的头像");
        return service.upload(session, expected_version, file.getBytes());
    }

    @PostMapping("/avatar/reset")
    public Profile reset(
            @RequestHeader(name = "Authorization", required = false) String auth, @RequestBody Version version) {
        return service.resetAvatar(principals.session(auth), version.expected_version());
    }

    @GetMapping(value = "/avatar", produces = "image/png")
    public ResponseEntity<byte[]> avatar(@RequestHeader(name = "Authorization", required = false) String auth) {
        return ResponseEntity.ok()
                .header("Cache-Control", "private, no-store")
                .header("X-Content-Type-Options", "nosniff")
                .body(service.avatar(principals.session(auth)));
    }

    @GetMapping("/addresses")
    public Addresses addresses(@RequestHeader(name = "Authorization", required = false) String auth) {
        return new Addresses(service.addresses(principals.session(auth)));
    }

    @PostMapping("/addresses")
    public Address create(
            @RequestHeader(name = "Authorization", required = false) String auth, @RequestBody EditAddress body) {
        return service.saveAddress(principals.session(auth), null, body);
    }

    @PostMapping("/addresses/{id}")
    public Address update(
            @RequestHeader(name = "Authorization", required = false) String auth,
            @PathVariable String id,
            @RequestBody EditAddress body) {
        return service.saveAddress(principals.session(auth), id, body);
    }

    @PostMapping("/addresses/{id}/delete")
    public ResponseEntity<Void> delete(
            @RequestHeader(name = "Authorization", required = false) String auth,
            @PathVariable String id,
            @RequestBody Version body) {
        service.deleteAddress(principals.session(auth), id, body.expected_version());
        return ResponseEntity.noContent().build();
    }

    @ExceptionHandler(Refused.class)
    public ResponseEntity<ApiError> refused(Refused e) {
        return ResponseEntity.status(e.status)
                .body(ApiError.of(
                        e.code, e.getMessage(), false, UUID.randomUUID().toString()));
    }
}
