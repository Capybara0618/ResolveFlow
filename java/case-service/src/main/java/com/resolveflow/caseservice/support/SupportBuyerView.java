package com.resolveflow.caseservice.support;

import java.util.ArrayList;
import java.util.HashSet;
import java.util.Set;
import tools.jackson.databind.JsonNode;

/** Validate display-only fields before persistence. None of these fields can execute an action. */
final class SupportBuyerView {
    private SupportBuyerView() {}

    static boolean valid(JsonNode answer) {
        if (!answer.has("buyer_view")) return true; // Old messages and producers remain readable.
        var view = answer.path("buyer_view");
        if (!keys(view, Set.of("version", "parts"))
                || view.size() != 2
                || !view.path("version").asString().equals("buyer-view-v1")
                || !view.path("parts").isArray()
                || view.path("parts").isEmpty()
                || view.path("parts").size() > 8) return false;
        var ids = new HashSet<String>();
        var actions = new HashSet<String>();
        var sections = new ArrayList<String>();
        for (var part : view.path("parts")) {
            if (!keys(part, Set.of("task_id", "text", "guidance", "action"))
                    || !part.path("task_id").isString()
                    || !part.path("task_id").asString().matches("[a-zA-Z0-9_-]{1,32}")
                    || !ids.add(part.path("task_id").asString())
                    || !text(part.path("text"), 4000)) return false;
            sections.add(part.path("text").asString());
            if (part.has("guidance")) {
                if (part.has("action") || !text(part.path("guidance"), 1000)) return false;
                sections.add(part.path("guidance").asString());
            }
            if (part.has("action")) {
                if (!part.path("action").isString()) return false;
                String action = part.path("action").asString();
                if (!actions.add(action)) return false;
                String reason =
                        switch (action) {
                            case "REFUND_APPLICATION" -> "refund_summary";
                            case "MERCHANT_REVIEW" -> "handoff_summary";
                            default -> null;
                        };
                if (reason == null || !text(answer.path(reason), 2000)) return false;
            }
        }
        // A presentation cannot hide or replace the published buyer message/history/share text.
        return actions.contains("REFUND_APPLICATION") == text(answer.path("refund_summary"), 2000)
                && actions.contains("MERCHANT_REVIEW") == text(answer.path("handoff_summary"), 2000)
                && String.join("\n\n", sections).equals(answer.path("text").asString());
    }

    private static boolean keys(JsonNode node, Set<String> allowed) {
        if (!node.isObject()) return false;
        for (var entry : node.properties()) if (!allowed.contains(entry.getKey())) return false;
        return true;
    }

    private static boolean text(JsonNode node, int max) {
        return node.isString()
                && !node.asString().isBlank()
                && node.asString().codePointCount(0, node.asString().length()) <= max;
    }
}
