package com.resolveflow.commerce.publicapi;

import com.resolveflow.commerce.catalog.ProductReviewService;
import com.resolveflow.shared.shopping.ProductReviewWire.*;
import org.springframework.web.bind.annotation.*;

@RestController
public class PublicReviewController {
    private final CommerceAccess access;
    private final ProductReviewService reviews;
    private final ReviewWriteLimiter limiter;

    public PublicReviewController(CommerceAccess access, ProductReviewService reviews, ReviewWriteLimiter limiter) {
        this.access = access;
        this.reviews = reviews;
        this.limiter = limiter;
    }

    @GetMapping("/api/v1/shop/orders/lines/{line_id}/review")
    public Own own(
            @RequestHeader(name = "Authorization", required = false) String auth,
            @PathVariable("line_id") String line) {
        return CommerceAccess.owned(access.buyer(auth), s -> reviews.own(line, s.merchantId(), s.buyerId()));
    }

    @PostMapping("/api/v1/shop/orders/lines/{line_id}/review")
    public Review save(
            @RequestHeader(name = "Authorization", required = false) String auth,
            @PathVariable("line_id") String line,
            @RequestBody Write body) {
        var actor = access.buyer(auth);
        limiter.check(actor.principal(), ReviewWriteLimiter.Action.WRITE);
        return CommerceAccess.owned(actor, s -> reviews.save(line, new Command(s.merchantId(), s.buyerId(), body)));
    }

    @GetMapping("/api/v1/merchant/reviews")
    public Page merchant(
            @RequestHeader(name = "Authorization", required = false) String auth,
            @RequestParam(required = false) Long before,
            @RequestParam(required = false) Integer limit) {
        return reviews.merchantPage(access.merchant(auth).merchantId(), before, limit);
    }

    @PostMapping("/api/v1/merchant/reviews/{review_id}/reply")
    public Review reply(
            @RequestHeader(name = "Authorization", required = false) String auth,
            @PathVariable("review_id") long id,
            @RequestBody Reply body) {
        var p = access.merchant(auth);
        limiter.check(p, ReviewWriteLimiter.Action.REPLY);
        return reviews.reply(id, new ReplyCommand(p.merchantId(), body));
    }
}
