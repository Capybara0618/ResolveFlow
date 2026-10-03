package com.resolveflow.commerce.catalog;

import com.resolveflow.shared.shopping.MultiCheckoutWire.Line;
import java.util.List;
import java.util.Map;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Service;

/** Immutable snapshots. Old SINGLE drafts retain their original flattened snapshot. */
@Service
public class DraftLines {
    private final JdbcTemplate jdbc;

    public DraftLines(JdbcTemplate jdbc) {
        this.jdbc = jdbc;
    }

    public List<Line> read(Map<String, Object> draft) {
        if ("SINGLE".equals(draft.get("kind")))
            return List.of(new Line(
                    (String) draft.get("sku_id"),
                    (String) draft.get("product_id"),
                    (String) draft.get("product_name"),
                    (String) draft.get("variant"),
                    (String) draft.get("asset_key"),
                    (String) draft.get("category"),
                    ((Number) draft.get("quantity")).intValue(),
                    ((Number) draft.get("unit_amount")).longValue(),
                    ((Number) draft.get("total_amount")).longValue(),
                    ((Number) draft.get("sku_version")).longValue()));
        var lines = jdbc.query(
                "SELECT * FROM checkout_draft_line WHERE draft_id=? ORDER BY sku_id",
                (rs, n) -> new Line(
                        rs.getString("sku_id"),
                        rs.getString("product_id"),
                        rs.getString("product_name"),
                        rs.getString("variant"),
                        rs.getString("asset_key"),
                        rs.getString("category"),
                        rs.getInt("quantity"),
                        rs.getLong("unit_amount"),
                        rs.getLong("line_amount"),
                        rs.getLong("sku_version")),
                draft.get("draft_id"));
        if (lines.size() != ((Number) draft.get("line_count")).intValue()
                || lines.isEmpty()
                || lines.stream().mapToLong(Line::lineAmount).sum() != ((Number) draft.get("total_amount")).longValue())
            throw new IllegalStateException("checkout snapshot is incomplete");
        return lines;
    }

    public String publishedId(Map<String, Object> draft, String attempt, String sku, String firstLine) {
        if ("SINGLE".equals(draft.get("kind"))) return firstLine;
        return jdbc.queryForObject(
                "SELECT line_id FROM checkout_payment_line WHERE attempt_id=? AND sku_id=?",
                String.class,
                attempt,
                sku);
    }
}
