package com.resolveflow.commerce.catalog;

import com.resolveflow.shared.shopping.ManagementWire.Product;
import java.util.concurrent.ExecutionException;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.TimeoutException;
import org.apache.kafka.clients.admin.NewTopic;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.boot.ApplicationRunner;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Profile;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.kafka.annotation.KafkaListener;
import org.springframework.kafka.config.TopicBuilder;
import org.springframework.kafka.core.KafkaTemplate;
import org.springframework.kafka.listener.DefaultErrorHandler;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.scheduling.concurrent.ThreadPoolTaskScheduler;
import org.springframework.stereotype.Component;
import org.springframework.transaction.support.TransactionSynchronizationManager;
import org.springframework.util.backoff.FixedBackOff;
import tools.jackson.databind.ObjectMapper;

@Component
@Profile("backend-search")
public class CatalogSearchEvents {
    private static final Logger LOG = LoggerFactory.getLogger(CatalogSearchEvents.class);
    private static final int BACKFILL_PAGE = 200;

    private record Pending(long id, String productId, String payload) {}

    private final JdbcTemplate jdbc;
    private final KafkaTemplate<String, String> kafka;
    private final ObjectMapper json;
    private final CatalogSearchIndex index;
    private final String topic;

    public CatalogSearchEvents(
            JdbcTemplate jdbc,
            KafkaTemplate<String, String> kafka,
            ObjectMapper json,
            CatalogSearchIndex index,
            @Value("${resolveflow.catalog.search.topic}") String topic) {
        this.jdbc = jdbc;
        this.kafka = kafka;
        this.json = json;
        this.index = index;
        this.topic = topic;
    }

    @Bean
    NewTopic catalogSearchTopic() {
        return TopicBuilder.name(topic).partitions(2).replicas(1).build();
    }

    @Bean(defaultCandidate = false)
    ThreadPoolTaskScheduler catalogSearchScheduler() {
        var scheduler = new ThreadPoolTaskScheduler();
        scheduler.setThreadNamePrefix("catalog-search-outbox-");
        return scheduler;
    }

    @Bean
    DefaultErrorHandler catalogSearchRetry() {
        var handler = new DefaultErrorHandler(new FixedBackOff(1000, FixedBackOff.UNLIMITED_ATTEMPTS));
        // A failed index write must leave the offset uncommitted, including during an ES outage.
        handler.setClassifications(java.util.Map.of(), true);
        return handler;
    }

    @Bean
    ApplicationRunner initializeSearchIndex(@Value("${resolveflow.catalog.search.backfill}") boolean backfill) {
        return args -> {
            index.ensureIndex();
            if (backfill) backfill();
        };
    }

    void record(Product product) {
        if (!TransactionSynchronizationManager.isActualTransactionActive())
            throw new IllegalStateException("Catalog search outbox requires the catalog write transaction");
        var document = new CatalogSearchIndex.Document(
                product.product_id(),
                product.store_id(),
                product.name(),
                product.description(),
                product.category(),
                product.listed(),
                product.version());
        jdbc.update(
                "INSERT INTO catalog_search_outbox(product_id,product_version,payload) VALUES(?,?,?)",
                document.id(),
                document.version(),
                json.writeValueAsString(document));
    }

    @Scheduled(
            fixedDelayString = "${resolveflow.catalog.search.poll-ms:500}",
            initialDelay = 1000,
            scheduler = "catalogSearchScheduler")
    void publish() {
        var pending = jdbc.query("""
                SELECT event_id, product_id, payload FROM catalog_search_outbox
                ORDER BY event_id LIMIT 20
                """, (row, number) -> new Pending(row.getLong(1), row.getString(2), row.getString(3)));
        for (Pending event : pending) {
            try {
                kafka.send(topic, event.productId(), event.payload()).get(5, TimeUnit.SECONDS);
            } catch (InterruptedException interrupted) {
                Thread.currentThread().interrupt();
                return;
            } catch (ExecutionException | TimeoutException | RuntimeException failure) {
                LOG.warn(
                        "Catalog search event {} remains pending ({})",
                        event.id(),
                        failure.getClass().getSimpleName());
                return;
            }
            jdbc.update("DELETE FROM catalog_search_outbox WHERE event_id=?", event.id());
        }
    }

    @KafkaListener(
            topics = "${resolveflow.catalog.search.topic}",
            groupId = "${resolveflow.catalog.search.consumer-group}",
            autoStartup = "${resolveflow.catalog.search.consumer-enabled}")
    void indexEvent(String payload) {
        var document = json.readValue(payload, CatalogSearchIndex.Document.class);
        index.apply(document);
    }

    private void backfill() {
        String after = "";
        while (true) {
            var page = jdbc.query(
                    """
                    SELECT product_id,store_id,name,description,category,listed,version
                    FROM catalog_product WHERE product_id>? ORDER BY product_id LIMIT ?
                    """,
                    (row, number) -> new CatalogSearchIndex.Document(
                            row.getString(1),
                            row.getString(2),
                            row.getString(3),
                            row.getString(4),
                            row.getString(5),
                            row.getBoolean(6),
                            row.getLong(7)),
                    after,
                    BACKFILL_PAGE);
            for (var document : page) index.apply(document);
            if (page.size() < BACKFILL_PAGE) return;
            after = page.getLast().id();
        }
    }
}
