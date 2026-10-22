package com.resolveflow.commerce.catalog;

import static org.assertj.core.api.Assertions.assertThat;

import com.resolveflow.commerce.CommerceDatabaseTest;
import java.lang.reflect.InvocationTargetException;
import java.lang.reflect.Proxy;
import java.sql.Connection;
import java.sql.SQLException;
import java.time.Clock;
import java.util.concurrent.atomic.AtomicInteger;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.datasource.DelegatingDataSource;

class ShoppingBatchDatabaseTest extends CommerceDatabaseTest {
    @Autowired
    JdbcTemplate jdbc;

    @Test
    void listingUsesTwoStatementsRegardlessOfProductCountAndPreservesDetails() {
        AtomicInteger statements = new AtomicInteger();
        var source = new DelegatingDataSource(jdbc.getDataSource()) {
            @Override
            public Connection getConnection() throws SQLException {
                var connection = super.getConnection();
                return (Connection) Proxy.newProxyInstance(
                        Connection.class.getClassLoader(), new Class<?>[] {Connection.class}, (proxy, method, args) -> {
                            if (method.getName().equals("prepareStatement")) statements.incrementAndGet();
                            try {
                                return method.invoke(connection, args);
                            } catch (InvocationTargetException e) {
                                throw e.getCause();
                            }
                        });
            }
        };
        var shop = new ShoppingService(new JdbcTemplate(source), Clock.systemUTC());
        var one = shop.products(null, null, null, null, 1);
        assertThat(statements.getAndSet(0)).isEqualTo(2);
        var four = shop.products(null, null, null, null, 4);
        assertThat(statements.getAndSet(0)).isEqualTo(2);
        assertThat(four.items()).hasSize(4);
        assertThat(four.items().getFirst()).isEqualTo(one.items().getFirst());
        for (var product : four.items()) assertThat(product).isEqualTo(shop.product(product.productId()));
        statements.set(0);
        assertThat(shop.products("does-not-exist", null, null, null, 4).items()).isEmpty();
        assertThat(statements.get()).isEqualTo(1);
    }
}
