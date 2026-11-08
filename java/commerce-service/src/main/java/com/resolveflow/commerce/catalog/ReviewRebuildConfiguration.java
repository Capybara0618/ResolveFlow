package com.resolveflow.commerce.catalog;

import java.time.Duration;
import org.redisson.Redisson;
import org.redisson.api.RedissonClient;
import org.redisson.client.codec.StringCodec;
import org.redisson.config.Config;
import org.redisson.config.EqualJitterDelay;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.boot.autoconfigure.condition.ConditionalOnExpression;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;

/** Separate lock client; Spring Data Redis continues to own cache values and Lua rate limits. */
@Configuration(proxyBeanMethods = false)
public class ReviewRebuildConfiguration {
    @Bean(destroyMethod = "shutdown")
    @ConditionalOnExpression(
            "(${resolveflow.product-reviews.cache-enabled:false} or ${resolveflow.catalog.cache-enabled:false}) and ${resolveflow.product-reviews.rebuild-lock-enabled:true}")
    RedissonClient reviewRebuildClient(
            @Value("${spring.data.redis.host:127.0.0.1}") String host,
            @Value("${spring.data.redis.port:6379}") int port,
            @Value("${spring.data.redis.username:}") String username,
            @Value("${spring.data.redis.password:}") String password,
            @Value("${spring.data.redis.database:0}") int database,
            @Value("${spring.data.redis.ssl.enabled:false}") boolean ssl) {
        return Redisson.create(
                configuration((ssl ? "rediss://" : "redis://") + host + ":" + port, username, password, database));
    }

    static Config configuration(String address, String username, String password, int database) {
        Config config = new Config();
        config.setLazyInitialization(true)
                .setCodec(StringCodec.INSTANCE)
                .setThreads(2)
                .setNettyThreads(2);
        var server = config.useSingleServer()
                .setAddress(address)
                .setDatabase(database)
                .setConnectTimeout(100)
                .setTimeout(100)
                .setRetryAttempts(0)
                .setReconnectionDelay(new EqualJitterDelay(Duration.ofMillis(100), Duration.ofMillis(500)))
                .setConnectionMinimumIdleSize(1)
                .setConnectionPoolSize(4)
                .setSubscriptionConnectionMinimumIdleSize(1)
                .setSubscriptionConnectionPoolSize(2);
        if (!username.isEmpty()) server.setUsername(username);
        if (!password.isEmpty()) server.setPassword(password);
        return config;
    }
}
