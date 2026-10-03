package com.resolveflow.caseservice.casefile;

import com.resolveflow.caseservice.order.RequestPrincipalResolver;
import org.springframework.web.bind.annotation.*;

@RestController
@RequestMapping("/api/v1/customer")
public class CustomerCaseController {
    private final RequestPrincipalResolver principals;
    private final CustomerCaseService customers;

    public CustomerCaseController(RequestPrincipalResolver principals, CustomerCaseService customers) {
        this.principals = principals;
        this.customers = customers;
    }

    @GetMapping("/cases")
    public CustomerCaseService.Page list(
            @RequestHeader(name = "Authorization", required = false) String auth,
            @RequestParam(required = false) String view,
            @RequestParam(name = "line_id", required = false) String line,
            @RequestParam(required = false) String cursor,
            @RequestParam(required = false) Integer limit) {
        return customers.list(principals.resolve(auth), view, line, cursor, limit);
    }

    @GetMapping("/cases/{case_id}")
    public CustomerCaseService.Detail read(
            @RequestHeader(name = "Authorization", required = false) String auth, @PathVariable("case_id") String id) {
        return customers.read(principals.forCase(auth, id), id);
    }

    @GetMapping("/order-lines/{line_id}")
    public CustomerCaseService.Line line(
            @RequestHeader(name = "Authorization", required = false) String auth, @PathVariable("line_id") String id) {
        return customers.line(principals.forLine(auth, id), id);
    }

    @PostMapping("/cases/{case_id}/answers")
    public CustomerCaseService.Detail answer(
            @RequestHeader(name = "Authorization", required = false) String auth,
            @PathVariable("case_id") String id,
            @RequestHeader(name = "If-Match", required = false) String version,
            @RequestBody CustomerCaseService.Answer body) {
        return customers.answer(principals.forCase(auth, id), id, version, body);
    }
}
