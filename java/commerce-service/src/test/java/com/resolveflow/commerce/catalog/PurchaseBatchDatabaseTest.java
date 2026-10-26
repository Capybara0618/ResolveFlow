package com.resolveflow.commerce.catalog;

import static org.assertj.core.api.Assertions.*;

import com.resolveflow.commerce.CommerceDatabaseTest;
import com.resolveflow.shared.shopping.CheckoutWire.*;
import java.lang.reflect.*;
import java.nio.charset.StandardCharsets;
import java.nio.file.*;
import java.sql.*;
import java.time.*;
import java.util.*;
import javax.sql.DataSource;
import org.junit.jupiter.api.*;
import org.springframework.aop.framework.ProxyFactory;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.datasource.*;
import org.springframework.transaction.annotation.AnnotationTransactionAttributeSource;
import org.springframework.transaction.interceptor.TransactionInterceptor;
import tools.jackson.databind.ObjectMapper;

class PurchaseBatchDatabaseTest extends CommerceDatabaseTest {
    static final String STORE = "M-1001", BUYER = "D3-PURCHASE";
    static final Instant NOW = Instant.parse("2026-10-26T08:00:00Z");

    @Autowired
    JdbcTemplate database;

    @Autowired
    SimulatedCheckoutProvider provider;

    PurchaseReads reads;
    final List<String> executions = new ArrayList<>();
    final List<Map<String, Object>> boundStatements = new ArrayList<>();
    JdbcTemplate measured;
    boolean counting;
    Runnable afterCandidate;

    static String id(String value) {
        return UUID.nameUUIDFromBytes(value.getBytes(StandardCharsets.UTF_8)).toString();
    }

    static Object invoke(Object target, Method method, Object[] args) throws Throwable {
        try {
            return method.invoke(target, args);
        } catch (InvocationTargetException e) {
            throw e.getCause();
        }
    }

    @BeforeEach
    void setup() {
        if (database.queryForObject("SELECT COUNT(*) FROM checkout_draft WHERE customer_id=?", Integer.class, BUYER)
                == 0) {
            for (int i = 0; i < 64; i++) fixture(i, STORE, BUYER);
            for (int i = 64; i < 67; i++) fixture(i, "M-1002", BUYER);
            for (int i = 67; i < 70; i++) fixture(i, STORE, "D3-OTHER");
        }
        DataSource source = new DelegatingDataSource(database.getDataSource()) {
            @Override
            public Connection getConnection() throws SQLException {
                var connection = super.getConnection();
                connection.setTransactionIsolation(Connection.TRANSACTION_READ_COMMITTED);
                return (Connection) Proxy.newProxyInstance(
                        Connection.class.getClassLoader(), new Class<?>[] {Connection.class}, (p, m, a) -> {
                            Object value = invoke(connection, m, a);
                            if (m.getName().equals("prepareStatement")
                                    && value instanceof PreparedStatement statement) {
                                String sql = (String) a[0];
                                var bindings = new TreeMap<Integer, Object>();
                                return Proxy.newProxyInstance(
                                        PreparedStatement.class.getClassLoader(),
                                        new Class<?>[] {PreparedStatement.class},
                                        (p2, m2, a2) -> {
                                            Object result = invoke(statement, m2, a2);
                                            if (m2.getName().startsWith("set")
                                                    && a2 != null
                                                    && a2.length >= 2
                                                    && a2[0] instanceof Integer index)
                                                bindings.put(index, m2.getName().equals("setNull") ? null : a2[1]);
                                            if (counting && m2.getName().startsWith("execute")) {
                                                assertThat(connection.getTransactionIsolation())
                                                        .isEqualTo(Connection.TRANSACTION_REPEATABLE_READ);
                                                assertThat(connection.isReadOnly())
                                                        .isTrue();
                                                executions.add(sql);
                                                boundStatements.add(Map.of(
                                                        "sql", sql, "bindings", new ArrayList<>(bindings.values())));
                                                if (sql.contains("SELECT id FROM (") && afterCandidate != null)
                                                    afterCandidate.run();
                                            }
                                            return result;
                                        });
                            }
                            return value;
                        });
            }
        };
        var jdbc = new JdbcTemplate(source);
        measured = jdbc;
        var clock = Clock.fixed(NOW, ZoneOffset.UTC);
        var lines = new DraftLines(jdbc);
        var shop = new ShoppingService(jdbc, clock);
        var manager = new DataSourceTransactionManager(source);
        var payment = new CheckoutPayments(jdbc, shop, lines, provider, clock, manager);
        var proxy = new ProxyFactory(new PurchaseReads(jdbc, shop, payment, clock, lines));
        proxy.setProxyTargetClass(true);
        proxy.addAdvice(new TransactionInterceptor(manager, new AnnotationTransactionAttributeSource()));
        reads = (PurchaseReads) proxy.getProxy();
    }

    void fixture(int n, String merchant, String customer) {
        int state = n % 8, count = state == 0 || state == 6 ? 1 : n % 3 + 1;
        String draft = id("draft-" + n), order = id("order-" + n), first = "D3-" + n + "-0";
        String status =
                switch (state) {
                    case 1 -> "PAYMENT_PENDING";
                    case 2, 6, 7 -> "PAID";
                    case 3, 5 -> "CANCELLED";
                    default -> "WAITING_PAYMENT";
                };
        long amount = 0;
        for (int j = 0; j < count; j++) amount += 100 + j * 50;
        var created = Timestamp.from(NOW.minusSeconds(3600));
        boolean paid = status.equals("PAID");
        if (paid) {
            database.update(
                    "INSERT INTO orders(order_id,merchant_id,customer_id,order_status,currency,paid_at,created_at) VALUES(?,?,?,'PAID','CNY',?,?)",
                    order,
                    merchant,
                    customer,
                    created,
                    created);
            database.update(
                    "INSERT INTO payment_ledger VALUES(?,?,?,?,1)",
                    order,
                    amount,
                    state == 6 ? 50 : state == 7 ? amount : 0,
                    state == 2 ? 50 : 0);
            for (int j = 0; j < count; j++)
                database.update(
                        "INSERT INTO order_line(line_id,order_id,merchant_id,customer_id,sku,category,quantity,line_paid_amount,currency,paid_at,order_status,version,product_name,variant_text) VALUES(?,?,?,?,?,'electronics',1,?,'CNY',?,'PAID',1,?,?)",
                        "D3-" + n + "-" + j,
                        order,
                        merchant,
                        customer,
                        "D3-SKU-" + j,
                        100 + j * 50,
                        created,
                        "snapshot-" + n,
                        "variant-" + j);
        }
        if (state == 7) return;
        boolean multi = state != 0 && state != 6;
        database.update(
                "INSERT INTO checkout_draft(draft_id,merchant_id,customer_id,idempotency_key,product_id,product_name,store_name,asset_key,sku_id,variant,quantity,unit_amount,total_amount,sku_version,created_at,expires_at,category,status,order_id,line_id,paid_at,kind,line_count,cart_revision,multiline_request_hash,close_reason) VALUES(?,?,?,?,?,?,?,'headphones','D3-SKU-0','variant-0',1,100,?,1,?,?,'electronics',?,?,?,?,?,?,?, ?,?)",
                draft,
                merchant,
                customer,
                "D3-" + n,
                "P-1001",
                "snapshot-" + n,
                "frozen store",
                amount,
                created,
                Timestamp.from(state == 4 ? NOW.minusSeconds(1) : NOW.plusSeconds(3600)),
                status,
                paid ? order : null,
                paid ? first : null,
                paid ? created : null,
                multi ? "MULTI" : "SINGLE",
                count,
                multi ? 0L : null,
                multi ? "a".repeat(64) : null,
                state == 5 ? "EXPIRED" : null);
        if (multi)
            for (int j = 0; j < count; j++)
                database.update(
                        "INSERT INTO checkout_draft_line VALUES(?,?,?,?,?,?,'electronics',1,?,?,1)",
                        draft,
                        "D3-SKU-" + j,
                        "P-1001",
                        "snapshot-" + n,
                        "variant-" + j,
                        "headphones",
                        100 + j * 50,
                        100 + j * 50);
        if (state == 0 || state == 3 || state == 4 || state == 5) return;
        database.update(
                "INSERT INTO checkout_payment_attempt(attempt_id,draft_id,sequence_no,idempotency_key,total_amount,currency,status,order_id,line_id,created_at,finished_at) VALUES(?,?,1,'failed',?,'CNY','FAILED',?,?,?,?)",
                id("failed-" + n),
                draft,
                amount,
                id("unused-" + n),
                "D3-old-" + n,
                created,
                created);
        String attempt = id("attempt-" + n);
        database.update(
                "INSERT INTO checkout_payment_attempt(attempt_id,draft_id,sequence_no,idempotency_key,total_amount,currency,status,order_id,line_id,created_at,finished_at,paid_at) VALUES(?,?,2,'latest',?,'CNY',?,?,?,?,?,?)",
                attempt,
                draft,
                amount,
                paid ? "SUCCEEDED" : "UNKNOWN",
                order,
                first,
                created,
                paid ? created : null,
                paid ? created : null);
        if (multi)
            for (int j = 0; j < count; j++)
                database.update(
                        "INSERT INTO checkout_payment_line VALUES(?,?,?)", attempt, "D3-SKU-" + j, "D3-" + n + "-" + j);
    }

    Purchases page(String merchant, String customer, String filter, String cursor, int size) {
        executions.clear();
        boundStatements.clear();
        counting = true;
        try {
            return reads.list(merchant, customer, filter, cursor, size);
        } finally {
            counting = false;
        }
    }

    @Test
    void repeatedPagesPreserveOriginalDetailsWithBoundedSql() throws Exception {
        var rows = new ArrayList<Map<String, Object>>();
        for (int size : List.of(1, 24, 48))
            for (int repeat = 0; repeat < 10; repeat++) {
                var page = page(STORE, BUYER, null, null, size);
                assertThat(page.items()).hasSize(size);
                int statements = executions.size();
                for (var item : page.items()) assertThat(item).isEqualTo(reads.read(item.purchaseId(), STORE, BUYER));
                rows.add(Map.of(
                        "size",
                        size,
                        "repeat",
                        repeat,
                        "sql_count",
                        statements,
                        "executed_sql",
                        List.copyOf(executions),
                        "projection",
                        page));
            }
        String output = System.getProperty("resolveflow.purchase.output");
        if (output != null) {
            Path file = Path.of(output);
            Files.createDirectories(file.getParent());
            Files.writeString(
                    file,
                    new ObjectMapper().writeValueAsString(rows),
                    StandardCharsets.UTF_8,
                    StandardOpenOption.CREATE_NEW);
        }
        if (!Boolean.getBoolean("resolveflow.purchase.baseline"))
            assertThat(rows.stream().map(row -> (int) row.get("sql_count")).toList())
                    .allSatisfy(count -> assertThat(count).isLessThanOrEqualTo(8));
    }

    @Test
    void filtersSameTimePaginationAndOtherScopesKeepOriginalProjection() {
        for (String filter :
                Arrays.asList(null, "WAITING_PAYMENT", "PAYMENT_PENDING", "PAID", "CANCELLED", "EXPIRED")) {
            var all = page(STORE, BUYER, filter, null, 48);
            var seen = new ArrayList<Purchase>();
            String cursor = null;
            do {
                var next = page(STORE, BUYER, filter, cursor, 1);
                seen.addAll(next.items());
                cursor = next.nextCursor();
            } while (cursor != null);
            assertThat(seen).doesNotHaveDuplicates();
            assertThat(all.items()).isEqualTo(seen.subList(0, Math.min(48, seen.size())));
            for (var item : seen) {
                assertThat(item).isEqualTo(reads.read(item.purchaseId(), STORE, BUYER));
                if (filter != null) assertThat(item.status()).isEqualTo(filter);
                assertThatThrownBy(() -> reads.read(item.purchaseId(), STORE, "D3-OTHER"))
                        .isInstanceOf(ShoppingService.Refused.class);
                assertThatThrownBy(() -> reads.read(item.purchaseId(), "M-1002", BUYER))
                        .isInstanceOf(ShoppingService.Refused.class);
            }
        }
        assertThat(page("M-1002", BUYER, null, null, 48).items()).hasSize(3);
        assertThat(page(STORE, "D3-OTHER", null, null, 48).items()).hasSize(3);
        assertThat(page(STORE, "missing-buyer", null, null, 48).items()).isEmpty();
        assertThat(executions).hasSize(1);
    }

    @Test
    void readSnapshotDoesNotMixLedgerCommittedAfterCandidateSelection() throws Exception {
        String order = id("order-2"), purchase = "draft:" + id("draft-2");
        afterCandidate = () -> {
            try (var writer = database.getDataSource().getConnection();
                    var update = writer.prepareStatement(
                            "UPDATE payment_ledger SET reserved_refund_amount=0,refunded_amount=paid_amount WHERE order_id=?")) {
                update.setString(1, order);
                update.executeUpdate();
            } catch (SQLException error) {
                throw new IllegalStateException(error);
            }
        };
        try {
            assertThat(page(STORE, BUYER, "PAID", null, 48).items())
                    .filteredOn(item -> item.purchaseId().equals(purchase))
                    .extracting(Purchase::refundStatus)
                    .containsExactly("IN_PROGRESS");
            assertThat(reads.read(purchase, STORE, BUYER).refundStatus()).isEqualTo("REFUNDED");
        } finally {
            afterCandidate = null;
            database.update(
                    "UPDATE payment_ledger SET refunded_amount=0,reserved_refund_amount=50 WHERE order_id=?", order);
        }
    }

    @Test
    void incompleteSnapshotsAndMissingPublishedMappingsCannotReturnPartialPage() {
        String draft = id("draft-2"), attempt = id("attempt-2");
        int count =
                database.queryForObject("SELECT line_count FROM checkout_draft WHERE draft_id=?", Integer.class, draft);
        try {
            database.update("UPDATE checkout_draft SET line_count=line_count+1 WHERE draft_id=?", draft);
            assertThatThrownBy(() -> reads.list(STORE, BUYER, "PAID", null, 48))
                    .isInstanceOf(IllegalStateException.class)
                    .hasMessage("checkout snapshot is incomplete");
            assertThatThrownBy(() -> reads.read("draft:" + draft, STORE, BUYER))
                    .isInstanceOf(IllegalStateException.class)
                    .hasMessage("checkout snapshot is incomplete");
        } finally {
            database.update("UPDATE checkout_draft SET line_count=? WHERE draft_id=?", count, draft);
        }
        try {
            database.update(
                    "UPDATE checkout_payment_line SET sku_id='D3-missing' WHERE attempt_id=? AND sku_id='D3-SKU-0'",
                    attempt);
            assertThatThrownBy(() -> reads.list(STORE, BUYER, "PAID", null, 48))
                    .isInstanceOf(IllegalStateException.class)
                    .hasMessage("published checkout line is missing");
        } finally {
            database.update(
                    "UPDATE checkout_payment_line SET sku_id='D3-SKU-0' WHERE attempt_id=? AND sku_id='D3-missing'",
                    attempt);
        }
    }

    @Test
    void failedLatestPaymentKeepsWaitingDraftAndHidesPlannedOrderIds() {
        String draft = id("draft-0"), attempt = id("new-failed-0");
        var at = Timestamp.from(NOW.minusSeconds(60));
        try {
            database.update(
                    "INSERT INTO checkout_payment_attempt(attempt_id,draft_id,sequence_no,idempotency_key,total_amount,currency,status,order_id,line_id,created_at,finished_at) VALUES(?,?,1,'new-failed',100,'CNY','FAILED',?,'D3-unpublished',?,?)",
                    attempt,
                    draft,
                    id("unpublished-order-0"),
                    at,
                    at);
            var page = reads.list(STORE, BUYER, "WAITING_PAYMENT", null, 48);
            var found = page.items().stream()
                    .filter(item -> item.purchaseId().equals("draft:" + draft))
                    .findFirst()
                    .orElseThrow();
            assertThat(found).isEqualTo(reads.read("draft:" + draft, STORE, BUYER));
            assertThat(found.payment().status()).isEqualTo("FAILED");
            assertThat(found.orderId()).isNull();
            assertThat(found.payment().orderId()).isNull();
            assertThat(found.payment().lineId()).isNull();
            assertThat(found.lines())
                    .allSatisfy(line -> assertThat(line.lineId()).isNull());
        } finally {
            database.update("DELETE FROM checkout_payment_attempt WHERE attempt_id=?", attempt);
        }
    }

    @Test
    void recordsActualPageStatementsAndExecutionPlans() throws Exception {
        var page = page(STORE, BUYER, null, null, 48);
        assertThat(page.items()).hasSize(48);
        assertThat(boundStatements).hasSize(8);
        var plans = new ArrayList<Map<String, Object>>();
        for (var statement : boundStatements) {
            String sql = (String) statement.get("sql");
            Object[] args = ((List<?>) statement.get("bindings")).toArray();
            var plan = measured.queryForList("EXPLAIN ANALYZE " + sql, args);
            assertThat(plan).isNotEmpty();
            plans.add(Map.of(
                    "sql",
                    sql,
                    "bindings",
                    Arrays.stream(args).map(Object::toString).toList(),
                    "plan",
                    plan));
        }
        String output = System.getProperty("resolveflow.purchase.plans");
        if (output != null) {
            Path file = Path.of(output);
            Files.createDirectories(file.getParent());
            Files.writeString(
                    file,
                    new ObjectMapper().writeValueAsString(plans),
                    StandardCharsets.UTF_8,
                    StandardOpenOption.CREATE_NEW);
        }
    }
}
