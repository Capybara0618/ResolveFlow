package com.resolveflow.commerce.catalog;

import com.resolveflow.shared.shopping.CheckoutWire.Purchase;
import java.util.*;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.core.namedparam.NamedParameterJdbcTemplate;

/** Shopping labels project existing payment/ledger/shipment facts; they confer no new rights. */
final class PurchaseStages {
    static final Set<String> FILTERS =
            Set.of("AWAITING_SHIPMENT", "AWAITING_RECEIPT", "COMPLETED", "AFTER_SALES", "LOGISTICS_UNKNOWN");
    static final String TABLE = """
        SELECT o.order_id,CASE
          WHEN g.refunded_amount>0 OR g.reserved_refund_amount>0 THEN 'AFTER_SALES'
          WHEN COUNT(l.line_id)=0 OR COUNT(s.line_id)<COUNT(l.line_id) THEN 'LOGISTICS_UNKNOWN'
          WHEN SUM(s.carrier_conclusion='DELIVERED')=COUNT(l.line_id) THEN 'COMPLETED'
          WHEN SUM(s.status='NOT_SHIPPED')=COUNT(l.line_id) THEN 'AWAITING_SHIPMENT'
          WHEN SUM(s.carrier_conclusion IN ('IN_TRANSIT','DELIVERED'))=COUNT(l.line_id) THEN 'AWAITING_RECEIPT'
          ELSE 'LOGISTICS_UNKNOWN' END stage
        FROM orders o JOIN payment_ledger g ON g.order_id=o.order_id
        LEFT JOIN order_line l ON l.order_id=o.order_id AND l.merchant_id=o.merchant_id AND l.buyer_id=o.buyer_id
        LEFT JOIN shipment s ON s.line_id=l.line_id
        WHERE o.merchant_id=? AND o.buyer_id=?
        GROUP BY o.order_id,g.refunded_amount,g.reserved_refund_amount
        """;

    static List<Purchase> enrich(List<Purchase> items, String merchant, String customer, JdbcTemplate db) {
        var ids = items.stream()
                .map(Purchase::orderId)
                .filter(Objects::nonNull)
                .distinct()
                .toList();
        var stages = new HashMap<String, String>();
        if (!ids.isEmpty()) {
            String query = TABLE.replace(
                    "o.merchant_id=? AND o.buyer_id=?",
                    "o.merchant_id=:merchant AND o.buyer_id=:customer AND o.order_id IN (:ids)");
            new NamedParameterJdbcTemplate(db)
                    .query(query, Map.of("merchant", merchant, "customer", customer, "ids", ids), r -> {
                        stages.put(r.getString("order_id"), r.getString("stage"));
                    });
        }
        return items.stream()
                .map(p -> new Purchase(
                        p.purchaseId(),
                        p.draftId(),
                        p.storeId(),
                        p.storeName(),
                        p.status(),
                        p.totalAmount(),
                        p.currency(),
                        p.createdAt(),
                        p.expiresAt(),
                        p.paidAt(),
                        p.orderId(),
                        p.lines(),
                        p.payment(),
                        p.refundStatus(),
                        p.status().equals("PAID") ? stages.getOrDefault(p.orderId(), "LOGISTICS_UNKNOWN") : p.status()))
                .toList();
    }
}
