package com.resolveflow.caseservice.casefile;

import static org.assertj.core.api.Assertions.assertThat;

import com.resolveflow.caseservice.internal.AgentCallbackRequest;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.UUID;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.Executors;
import java.util.concurrent.TimeUnit;
import java.util.stream.IntStream;
import java.util.stream.Stream;
import org.junit.jupiter.api.RepeatedTest;
import org.junit.jupiter.api.RepetitionInfo;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.Arguments;
import org.junit.jupiter.params.provider.MethodSource;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.context.annotation.Import;
import org.springframework.http.HttpHeaders;
import org.springframework.http.MediaType;
import tools.jackson.databind.ObjectMapper;

/** Real Case HTTP/MySQL matrix. Commerce eligibility is the existing explicit fixture stub. */
@Import(InputMovesRetireApprovalApiTest.StubCommerceConfiguration.class)
class ResumeAuthorizationMatrixApiTest extends InputMovesRetireApprovalApiTest {
    private static final ObjectMapper JSON = new ObjectMapper();

    @Autowired
    AuthorizationConsumptionService consumption;

    @Autowired
    AgentCallbackService callbacks;

    static Stream<Arguments> trials() {
        return IntStream.rangeClosed(1, 8)
                .boxed()
                .flatMap(v -> IntStream.range(0, 10).mapToObj(n -> Arguments.of("V" + v, n)));
    }

    @ParameterizedTest(name = "{0}-trial{1}")
    @MethodSource("trials")
    void expiredRevisionAndValidControl(String scenario, int trial) throws Exception {
        String caseId = openCase();
        String statement = null;
        if (scenario.equals("V2")) statement = appendStatement(caseId, "合成客户原始陈述");
        boolean alreadyApproved = java.util.List.of("V3", "V5", "V6").contains(scenario);
        String old = alreadyApproved ? submitAndApprove(caseId, "本轮合成有效授权") : submitProposal(caseId, "有效待审批授权，随后输入变化");
        int oldRevision = caseView(caseId).get("case").get("input_revision").asInt();
        var candidate = new AuthorizationRepository.DispatchCandidate(old, caseId);
        int rejected = 0;
        List<Map<String, Object>> attemptRecords = new ArrayList<>();
        if (scenario.equals("V2")) {
            rest.post()
                    .uri("/api/v1/cases/" + caseId + "/reviewed-evidence")
                    .header(HttpHeaders.AUTHORIZATION, "Bearer " + reviewer())
                    .contentType(MediaType.APPLICATION_JSON)
                    .body(Map.of(
                            "source_evidence_id",
                            statement,
                            "verification_result",
                            trial % 2 == 0 ? "CONFIRMED" : "REFUTED",
                            "reason",
                            "量化实验人工核验"))
                    .headers(h -> addReviewHeaders(h, caseId))
                    .exchange()
                    .expectStatus()
                    .isOk();
            rejectApproval(caseId, old, attemptRecords);
            rejected++;
        } else if (scenario.equals("V6")) {
            ordered(
                    () -> rest.post()
                            .uri("/api/v1/cases/" + caseId + "/cancel")
                            .header(HttpHeaders.AUTHORIZATION, "Bearer " + customer())
                            .contentType(MediaType.APPLICATION_JSON)
                            .body(Map.of("reason", "消费前撤销"))
                            .headers(h -> addReviewHeaders(h, caseId))
                            .exchange()
                            .expectStatus()
                            .isOk(),
                    () -> rejectConsumption(candidate, attemptRecords));
            rejected++;
        } else if (scenario.equals("V4") || scenario.equals("V5")) {
            ordered(() -> appendStatement(caseId, "屏障保证新输入提交先获胜"), () -> {
                if (scenario.equals("V4")) rejectApproval(caseId, old, attemptRecords);
                else rejectConsumption(candidate, attemptRecords);
            });
            rejected++;
        } else {
            appendStatement(caseId, "新的客户材料使原授权失效");
            if (scenario.equals("V3")) {
                rejectConsumption(candidate, attemptRecords);
            } else if (scenario.equals("V7")) {
                var receipt = callbacks.receive(
                        caseId,
                        new AgentCallbackRequest(
                                UUID.randomUUID().toString(),
                                UUID.randomUUID().toString(),
                                oldRevision,
                                "PROPOSAL",
                                JSON.createObjectNode(),
                                null));
                assertThat(receipt.disposition()).isEqualTo(AgentCallback.Disposition.STALE);
                assertThat(jdbc.queryForObject(
                                "SELECT COUNT(*) FROM case_proposal WHERE case_id=? AND input_revision=?",
                                Integer.class,
                                caseId,
                                oldRevision))
                        .isEqualTo(1);
                rejectApproval(caseId, old, attemptRecords);
            } else {
                rejectApproval(caseId, old, attemptRecords);
            }
            rejected++;
            if (scenario.equals("V8")) {
                String second = submitProposal(caseId, "第二个版本待审批授权");
                appendStatement(caseId, "第三个版本材料");
                rejectApproval(caseId, second, attemptRecords);
                rejected++;
            }
        }
        assertThat(authorizationColumn("status", old)).isEqualTo("REVOKED");
        assertThat(jdbc.queryForObject(
                        "SELECT COUNT(*) FROM case_execution_command WHERE case_id=?", Integer.class, caseId))
                .isZero();
        String control = approvedCase();
        String current = authorisationOf(control);
        var valid = consumption.consume(new AuthorizationRepository.DispatchCandidate(current, control));
        assertThat(valid.dispatched()).isTrue();
        assertThat(refundOutboxCount(caseId)).isZero();
        assertThat(refundOutboxCount(control)).isEqualTo(1);
        assertThat(authorizationColumn("status", current)).isEqualTo("CONSUMED");
        assertThat(jdbc.queryForObject(
                        "SELECT COUNT(*) FROM case_execution_command WHERE case_id=?", Integer.class, control))
                .isEqualTo(1);
        Map<String, Object> result = new LinkedHashMap<>();
        result.put("case_id", caseId);
        result.put("authorization_id", old);
        result.put("old_revision", oldRevision);
        result.put(
                "final_revision",
                caseView(caseId).get("case").get("input_revision").asInt());
        result.put("attempt_records", attemptRecords);
        result.put("old_command_count", 0);
        result.put("old_outbox_count", refundOutboxCount(caseId));
        result.put("control_case_id", control);
        result.put("control_operation_id", valid.operationId());
        result.put("control_event_id", valid.eventId());
        result.put("control_status", authorizationColumn("status", current));
        result.put("control_command_count", 1);
        result.put("control_outbox_count", refundOutboxCount(control));
        result.put("callback_disposition", scenario.equals("V7") ? "STALE" : "NOT_APPLICABLE");
        assertThat(attemptRecords).hasSize(rejected);
        result.put("scenario", scenario);
        result.put("trial", trial);
        result.put("expired_attempts", rejected);
        result.put("expired_rejected", rejected);
        result.put("illegal_consumptions", 0);
        result.put("valid_consumptions", 1);
        result.put("old_authorization_status", authorizationColumn("status", old));
        result.put("real_mysql", true);
        result.put("commerce_context", "explicit eligibility fixture stub");
        record(scenario + "-" + trial, result);
    }

    @RepeatedTest(10)
    void consumedInputsCannotBeUpdated(RepetitionInfo repetition) throws Exception {
        String caseId = approvedCase();
        String authorization = authorisationOf(caseId);
        int beforeRevision = caseView(caseId).get("case").get("input_revision").asInt();
        var valid = consumption.consume(new AuthorizationRepository.DispatchCandidate(authorization, caseId));
        assertThat(valid.dispatched()).isTrue();
        rest.post()
                .uri("/api/v1/cases/" + caseId + "/evidence")
                .header(HttpHeaders.AUTHORIZATION, "Bearer " + customer())
                .contentType(MediaType.APPLICATION_JSON)
                .body(Map.of("text", "消费之后不能修改输入", "evidence_kind", "CUSTOMER_STATEMENT"))
                .headers(h -> addReviewHeaders(h, caseId))
                .exchange()
                .expectStatus()
                .isEqualTo(409);
        assertThat(authorizationColumn("status", authorization)).isEqualTo("CONSUMED");
        rest.post()
                .uri("/api/v1/cases/" + caseId + "/cancel")
                .header(HttpHeaders.AUTHORIZATION, "Bearer " + customer())
                .contentType(MediaType.APPLICATION_JSON)
                .body(Map.of("reason", "消费之后不能撤销"))
                .headers(h -> addReviewHeaders(h, caseId))
                .exchange()
                .expectStatus()
                .isEqualTo(409);
        int afterRevision = caseView(caseId).get("case").get("input_revision").asInt();
        assertThat(afterRevision).isEqualTo(beforeRevision);
        assertThat(refundOutboxCount(caseId)).isEqualTo(1);
        assertThat(jdbc.queryForObject(
                        "SELECT COUNT(*) FROM case_execution_command WHERE case_id=?", Integer.class, caseId))
                .isEqualTo(1);
        Map<String, Object> row = new LinkedHashMap<>();
        row.put("scenario", "consume-wins");
        row.put("trial", repetition.getCurrentRepetition());
        row.put("case_id", caseId);
        row.put("authorization_id", authorization);
        row.put("operation_id", valid.operationId());
        row.put("event_id", valid.eventId());
        row.put("revision_before", beforeRevision);
        row.put("revision_after", afterRevision);
        row.put("update_rejected", true);
        row.put("cancel_rejected", true);
        row.put("command_count", 1);
        row.put("outbox_count", refundOutboxCount(caseId));
        record("consume-wins-" + repetition.getCurrentRepetition(), row);
    }

    private int refundOutboxCount(String caseId) {
        return jdbc.queryForObject(
                "SELECT COUNT(*) FROM event_outbox WHERE event_type='RefundRequested' AND JSON_UNQUOTE(JSON_EXTRACT(envelope,'$.payload.case_id'))=?",
                Integer.class,
                caseId);
    }

    private void rejectConsumption(
            AuthorizationRepository.DispatchCandidate candidate, List<Map<String, Object>> records) {
        var answer = consumption.consume(candidate);
        assertThat(answer.dispatched()).isFalse();
        assertThat(answer.skippedBecause()).isNotBlank();
        records.add(Map.of(
                "action",
                "CONSUME",
                "dispatched",
                answer.dispatched(),
                "reason",
                answer.skippedBecause(),
                "authorization_id",
                candidate.authorizationId()));
    }

    private void rejectApproval(String caseId, String authorization, List<Map<String, Object>> records) {
        rest.post()
                .uri("/api/v1/cases/" + caseId + "/reviews")
                .header(HttpHeaders.AUTHORIZATION, "Bearer " + reviewer())
                .contentType(MediaType.APPLICATION_JSON)
                .body(Map.of(
                        "authorization_id",
                        authorization,
                        "authorization_version",
                        1,
                        "decision",
                        "APPROVE",
                        "reason",
                        "尝试审批旧输入"))
                .headers(h -> addReviewHeaders(h, caseId))
                .exchange()
                .expectStatus()
                .isEqualTo(409);
        records.add(Map.of("action", "APPROVE", "http_status", 409, "authorization_id", authorization));
    }

    private static void ordered(Runnable first, Runnable second) throws Exception {
        var committed = new CountDownLatch(1);
        try (var pool = Executors.newFixedThreadPool(2)) {
            var winner = pool.submit(() -> {
                first.run();
                committed.countDown();
            });
            var loser = pool.submit(() -> {
                try {
                    assertThat(committed.await(10, TimeUnit.SECONDS)).isTrue();
                    second.run();
                } catch (InterruptedException e) {
                    Thread.currentThread().interrupt();
                    throw new AssertionError(e);
                }
            });
            winner.get(15, TimeUnit.SECONDS);
            loser.get(15, TimeUnit.SECONDS);
        }
    }

    private static void record(String name, Map<String, Object> result) throws Exception {
        Path root = Path.of("").toAbsolutePath();
        while (root != null && !Files.isRegularFile(root.resolve("docs/core-scope.md"))) root = root.getParent();
        if (root == null) throw new IllegalStateException("repository root missing");
        Path path = root.resolve(System.getProperty(
                        "resolveflow.resume.authorization.report-dir",
                        "reports/resume-quantification-v1/authorization/attempt1")
                + "/" + name + ".json");
        Files.createDirectories(path.getParent());
        if (Files.exists(path)) throw new IllegalStateException("measurement is immutable: " + path);
        Files.writeString(path, JSON.writerWithDefaultPrettyPrinter().writeValueAsString(result) + "\n");
    }
}
