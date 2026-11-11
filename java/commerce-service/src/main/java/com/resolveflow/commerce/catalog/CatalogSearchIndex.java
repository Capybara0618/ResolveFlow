package com.resolveflow.commerce.catalog;

import com.resolveflow.shared.shopping.ShoppingWire.Product;
import com.resolveflow.shared.shopping.ShoppingWire.Products;
import java.util.ArrayList;
import java.util.Base64;
import java.util.List;
import java.util.Map;
import java.util.Objects;
import java.util.stream.Collectors;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.context.annotation.Profile;
import org.springframework.http.MediaType;
import org.springframework.http.client.SimpleClientHttpRequestFactory;
import org.springframework.stereotype.Component;
import org.springframework.web.client.RestClient;
import org.springframework.web.client.RestClientException;
import org.springframework.web.client.RestClientResponseException;
import tools.jackson.databind.JsonNode;
import tools.jackson.databind.ObjectMapper;
import tools.jackson.databind.node.ObjectNode;

@Component
@Profile("backend-search")
public class CatalogSearchIndex {
    record Document(
            String id, String store, String name, String description, String category, boolean listed, long version) {}

    record Cursor(String id, double score, int scope) {}

    private final ObjectMapper json;
    private final RestClient elastic;
    private final ShoppingService shopping;
    private final String index;

    public CatalogSearchIndex(
            ObjectMapper json,
            ShoppingService shopping,
            @Value("${resolveflow.catalog.search.url}") String url,
            @Value("${resolveflow.catalog.search.index}") String index) {
        if (!index.matches("[a-z][a-z0-9_-]{0,63}")) throw new IllegalArgumentException("Invalid search index name");
        this.json = json;
        this.shopping = shopping;
        this.index = index;
        var factory = new SimpleClientHttpRequestFactory();
        factory.setConnectTimeout(1000);
        factory.setReadTimeout(3000);
        this.elastic = RestClient.builder().baseUrl(url).requestFactory(factory).build();
    }

    void ensureIndex() {
        try {
            elastic.head().uri("/{index}", index).retrieve().toBodilessEntity();
            return;
        } catch (RestClientResponseException error) {
            if (error.getStatusCode().value() != 404) throw error;
        }
        try {
            elastic.put()
                    .uri("/{index}", index)
                    .contentType(MediaType.APPLICATION_JSON)
                    .body("""
                    {"settings":{"number_of_shards":1,"number_of_replicas":0},
                     "mappings":{"dynamic":"strict","properties":{
                        "id":{"type":"keyword"},"store":{"type":"keyword"},
                        "name":{"type":"text","analyzer":"cjk"},
                        "description":{"type":"text","analyzer":"cjk"},
                        "category":{"type":"keyword"},"listed":{"type":"boolean"},"version":{"type":"long"}
                     }}}
                    """)
                    .retrieve()
                    .toBodilessEntity();
        } catch (RestClientResponseException error) {
            if (!isError(error, 400, "resource_already_exists_exception")) throw error;
        }
    }

    void apply(Document document) {
        try {
            elastic.put()
                    .uri(
                            "/{index}/_doc/{id}?version={version}&version_type=external",
                            index,
                            document.id(),
                            document.version())
                    .contentType(MediaType.APPLICATION_JSON)
                    .body(document)
                    .retrieve()
                    .toBodilessEntity();
        } catch (RestClientResponseException error) {
            if (!isError(error, 409, "version_conflict_engine_exception")) throw error;
        }
    }

    private boolean isError(RestClientResponseException error, int status, String type) {
        return error.getStatusCode().value() == status
                && type.equals(json.readTree(error.getResponseBodyAsString())
                        .path("error")
                        .path("type")
                        .asString());
    }

    Products search(String query, String category, String store, String after, Integer suppliedLimit) {
        int limit = suppliedLimit == null ? 24 : suppliedLimit;
        if (query.length() > 80
                || limit < 1
                || limit > 48
                || store != null && !store.matches("[A-Za-z0-9_-]{1,64}")
                || category != null
                        && !List.of("electronics", "home", "outdoor").contains(category))
            throw new IllegalArgumentException("查询或分页参数超出范围");
        query = query.trim();
        int scope = Objects.hash(query, category, store);
        Cursor cursor = decode(after, scope);
        var products = new ArrayList<Product>();
        // Recheck stale candidates against MySQL while bounding work for one request.
        int window = Math.max(limit + 1, 24);
        for (int page = 0; page < 4; page++) {
            var hits = find(query, category, store, cursor, window, scope);
            var visible = shopping.searchProducts(hits.stream().map(Cursor::id).toList(), category, store).stream()
                    .collect(Collectors.toMap(Product::productId, p -> p));
            for (Cursor hit : hits) {
                var product = visible.get(hit.id());
                if (product != null && products.size() == limit)
                    return new Products(List.copyOf(products), encode(cursor));
                if (product != null) products.add(product);
                cursor = hit;
            }
            if (hits.size() < window) return new Products(List.copyOf(products), null);
        }
        return new Products(List.copyOf(products), encode(cursor));
    }

    private List<Cursor> find(String query, String category, String store, Cursor cursor, int window, int scope) {
        var filters = new ArrayList<Map<String, Object>>();
        filters.add(Map.of("term", Map.of("listed", true)));
        if (category != null) filters.add(Map.of("term", Map.of("category", category)));
        if (store != null) filters.add(Map.of("term", Map.of("store", store)));
        var match = Map.of("multi_match", Map.of("query", query, "fields", List.of("name^3", "description")));
        ObjectNode body = json.valueToTree(Map.of(
                "size",
                window,
                "_source",
                false,
                "track_total_hits",
                false,
                "sort",
                List.of(Map.of("_score", "desc"), Map.of("id", "asc")),
                "query",
                Map.of("bool", Map.of("filter", filters, "must", List.of(match)))));
        if (cursor != null) body.putArray("search_after").add(cursor.score()).add(cursor.id());
        try {
            JsonNode reply = elastic.post()
                    .uri("/{index}/_search", index)
                    .contentType(MediaType.APPLICATION_JSON)
                    .body(body)
                    .retrieve()
                    .body(JsonNode.class);
            if (reply == null
                    || reply.path("timed_out").asBoolean()
                    || reply.path("_shards").path("failed").asInt() != 0
                    || !reply.path("hits").path("hits").isArray()) throw unavailable();
            var hits = new ArrayList<Cursor>();
            for (JsonNode hit : reply.path("hits").path("hits")) {
                var sort = hit.path("sort");
                hits.add(new Cursor(sort.get(1).asString(), sort.get(0).asDouble(), scope));
            }
            return hits;
        } catch (RestClientException error) {
            throw unavailable();
        }
    }

    private String encode(Cursor cursor) {
        return Base64.getUrlEncoder().withoutPadding().encodeToString(json.writeValueAsBytes(cursor));
    }

    private Cursor decode(String value, int scope) {
        if (value == null) return null;
        try {
            if (!value.matches("[A-Za-z0-9_-]{1,192}")) throw new IllegalArgumentException();
            var cursor = json.readValue(Base64.getUrlDecoder().decode(value), Cursor.class);
            if (cursor.scope() != scope
                    || cursor.id() == null
                    || !cursor.id().matches("[A-Za-z0-9_-]{1,64}")
                    || !Double.isFinite(cursor.score())) throw new IllegalArgumentException();
            return cursor;
        } catch (RuntimeException error) {
            throw new IllegalArgumentException("搜索游标无效");
        }
    }

    private static ShoppingService.Refused unavailable() {
        return new ShoppingService.Refused(503, "SERVICE_UNAVAILABLE", "商品搜索暂不可用，请稍后重试");
    }
}
