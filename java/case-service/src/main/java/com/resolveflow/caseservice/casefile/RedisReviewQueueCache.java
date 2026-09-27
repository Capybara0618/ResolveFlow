package com.resolveflow.caseservice.casefile;

import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.time.Duration;
import java.util.HexFormat;
import java.util.Optional;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.stereotype.Component;
import tools.jackson.databind.ObjectMapper;

/** Only review-list presentation rows; approval and money paths never consult this cache. */
@Component
public class RedisReviewQueueCache implements ReviewQueueCache {

    static final Duration TTL = Duration.ofSeconds(2);

    private final StringRedisTemplate redis;
    private final ObjectMapper mapper;
    private final String namespace;

    public RedisReviewQueueCache(
            StringRedisTemplate redis,
            ObjectMapper mapper,
            @Value("${resolveflow.review-cache.namespace:rf:c11:review:v1}") String namespace) {
        this.redis = redis;
        this.mapper = mapper;
        this.namespace = namespace;
    }

    @Override
    public Optional<ReviewQueueService.Page> find(String merchantId, String cursor, int limit) {
        String encoded = redis.opsForValue().get(key(merchantId, cursor, limit));
        return encoded == null
                ? Optional.empty()
                : Optional.of(mapper.readValue(encoded, ReviewQueueService.Page.class));
    }

    @Override
    public void store(String merchantId, String cursor, int limit, ReviewQueueService.Page page) {
        redis.opsForValue().set(key(merchantId, cursor, limit), mapper.writeValueAsString(page), TTL);
    }

    private String key(String merchantId, String cursor, int limit) {
        String digest;
        try {
            digest = HexFormat.of()
                    .formatHex(MessageDigest.getInstance("SHA-256")
                            .digest((cursor == null ? "" : cursor).getBytes(StandardCharsets.UTF_8)));
        } catch (NoSuchAlgorithmException error) {
            throw new IllegalStateException("SHA-256 unavailable", error);
        }
        return namespace + ":" + merchantId + ":" + limit + ":" + digest;
    }
}
