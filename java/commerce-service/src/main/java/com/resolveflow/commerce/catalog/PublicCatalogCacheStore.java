package com.resolveflow.commerce.catalog;

import java.time.Duration;
import java.util.List;
import java.util.UUID;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.data.redis.core.script.DefaultRedisScript;
import org.springframework.stereotype.Component;
import tools.jackson.databind.ObjectMapper;

/** Redis-only generations prevent a query started before invalidation from refilling stale data. */
@Component
public class PublicCatalogCacheStore {
    private static final DefaultRedisScript<String> READ = new DefaultRedisScript<>("""
            local token=redis.call('GET',KEYS[1]) or ARGV[1]
            local value=redis.call('GET',KEYS[2])
            return cjson.encode({token=token,value=value or cjson.null})
            """, String.class);
    private static final DefaultRedisScript<Long> PUBLISH = new DefaultRedisScript<>("""
            local token=redis.call('GET',KEYS[1])
            if not token then
                token=ARGV[1]
                redis.call('SET',KEYS[1],token)
            end
            if token~=ARGV[1] then return 0 end
            redis.call('SET',KEYS[2],ARGV[2],'PX',ARGV[3])
            return 1
            """, Long.class);
    private static final DefaultRedisScript<Long> INVALIDATE = new DefaultRedisScript<>("""
            redis.call('SET',KEYS[1],ARGV[1])
            local deleted=0
            if ARGV[2]=='1' or ARGV[2]=='3' then deleted=deleted+redis.call('DEL',KEYS[2],KEYS[3]) end
            if ARGV[2]=='2' or ARGV[2]=='3' then deleted=deleted+redis.call('DEL',KEYS[4]) end
            return deleted
            """, Long.class);

    public record Snapshot(String token, String value) {}

    private final StringRedisTemplate redis;
    private final ObjectMapper json;
    private final String namespace;

    public PublicCatalogCacheStore(
            StringRedisTemplate redis,
            ObjectMapper json,
            @Value("${resolveflow.product-reviews.cache-namespace:rf:reviews:first:v1}") String namespace) {
        if (namespace == null || !namespace.matches("[A-Za-z0-9:_-]{1,120}"))
            throw new IllegalArgumentException("invalid public cache namespace");
        this.redis = redis;
        this.json = json;
        this.namespace = namespace;
    }

    String namespace() {
        return namespace;
    }

    private String generation(String product) {
        return namespace + ":aside-v2:generation:" + product;
    }

    String productKey(String product) {
        return namespace + ":aside-v2:product:" + product;
    }

    String presentationKey(String product) {
        return namespace + ":aside-v2:presentation:" + product;
    }

    String reviewKey(String product) {
        return namespace + ":aside-v2:reviews:" + product;
    }

    Snapshot read(String key, String product) {
        String result = redis.execute(
                READ, List.of(generation(product), key), UUID.randomUUID().toString());
        if (result == null) throw new IllegalStateException("missing cache snapshot");
        var snapshot = json.readValue(result, Snapshot.class);
        if (snapshot.token() == null || snapshot.token().isBlank())
            throw new IllegalStateException("invalid cache generation");
        return snapshot;
    }

    boolean publish(String key, String product, Snapshot snapshot, Object value, Duration ttl) {
        Long result = redis.execute(
                PUBLISH,
                List.of(generation(product), key),
                snapshot.token(),
                json.writeValueAsString(value),
                Long.toString(ttl.toMillis()));
        return Long.valueOf(1).equals(result);
    }

    void invalidate(String product, int targets) {
        if (targets < 1 || targets > 3) throw new IllegalArgumentException("invalid cache targets");
        Long result = redis.execute(
                INVALIDATE,
                List.of(generation(product), productKey(product), presentationKey(product), reviewKey(product)),
                UUID.randomUUID().toString(),
                Integer.toString(targets));
        if (result == null) throw new IllegalStateException("cache invalidation was not confirmed");
    }
}
