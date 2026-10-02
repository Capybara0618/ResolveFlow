package com.resolveflow.caseservice.auth;

import com.resolveflow.caseservice.order.RequestPrincipalResolver;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestHeader;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

/** Local merchant administration; authority: docs/staff-management.md. */
@RestController
@RequestMapping("/api/v1/admin/accounts")
public class StaffAdminController {
    private final StaffAdminService staff;
    private final RequestPrincipalResolver principals;

    public StaffAdminController(StaffAdminService staff, RequestPrincipalResolver principals) {
        this.staff = staff;
        this.principals = principals;
    }

    @GetMapping
    public StaffAdminService.Page list(
            @RequestHeader(name = "Authorization", required = false) String auth,
            @RequestParam(required = false) String query,
            @RequestParam(required = false) String role,
            @RequestParam(required = false) String status,
            @RequestParam(required = false) String cursor,
            @RequestParam(required = false) Integer limit) {
        return staff.list(principals.session(auth), query, role, status, cursor, limit);
    }

    @PostMapping
    public ResponseEntity<StaffAdminService.Mutation> create(
            @RequestHeader(name = "Authorization", required = false) String auth,
            @RequestBody StaffAdminService.Create body) {
        return ResponseEntity.status(201).body(staff.create(principals.session(auth), body));
    }

    @PostMapping("/{username}")
    public StaffAdminService.Mutation update(
            @RequestHeader(name = "Authorization", required = false) String auth,
            @PathVariable String username,
            @RequestHeader(name = "If-Match", required = false) String version,
            @RequestBody StaffAdminService.Update body) {
        return staff.update(principals.session(auth), username, version, body);
    }

    @PostMapping("/{username}/password")
    public StaffAdminService.Mutation password(
            @RequestHeader(name = "Authorization", required = false) String auth,
            @PathVariable String username,
            @RequestHeader(name = "If-Match", required = false) String version,
            @RequestBody StaffAdminService.Password body) {
        return staff.resetPassword(principals.session(auth), username, version, body);
    }

    @GetMapping("/{username}/history")
    public StaffAdminService.AuditPage history(
            @RequestHeader(name = "Authorization", required = false) String auth,
            @PathVariable String username,
            @RequestParam(required = false) String cursor,
            @RequestParam(required = false) Integer limit) {
        return staff.history(principals.session(auth), username, cursor, limit);
    }
}
