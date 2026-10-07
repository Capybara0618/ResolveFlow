package com.resolveflow.caseservice.casefile;

import static org.assertj.core.api.Assertions.assertThat;

import com.resolveflow.caseservice.internal.AgentCallbackRequest;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.LinkedHashMap;
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
            rejectApproval(caseId, old);
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
                    () -> assertThat(consumption.consume(candidate).dispatched())
                            .isFalse());
            rejected++;
        } else if (scenario.equals("V4") || scenario.equals("V5")) {
            ordered(() -> appendStatement(caseId, "屏障保证新输入提交先获胜"), () -> {
                if (scenario.equals("V4")) rejectApproval(caseId, old);
                else assertThat(consumption.consume(candidate).dispatched()).isFalse();
            });
            rejected++;
        } else {
            appendStatement(caseId, "新的客户材料使原授权失效");
            if (scenario.equals("V3")) {
                assertThat(consumption.consume(candidate).dispatched()).isFalse();
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
                rejectApproval(caseId, old);
            } else {
                rejectApproval(caseId, old);
            }
            rejected++;
            if (scenario.equals("V8")) {
                String second = submitProposal(caseId, "第二个版本待审批授权");
                appendStatement(caseId, "第三个版本材料");
                rejectApproval(caseId, second);
                rejected++;
            }
        }
        assertThat(authorizationColumn("status", old)).isEqualTo("REVOKED");
        assertThat(jdbc.queryForObject(
                        "SELECT COUNT(*) FROM case_execution_command WHERE case_id=?", Integer.class, caseId))
                .isZero();
        String control = approvedCase();
        String current = authorisationOf(control);
        assertThat(consumption
                        .consume(new AuthorizationRepository.DispatchCandidate(current, control))
                        .dispatched())
                .isTrue();
        assertThat(authorizationColumn("status", current)).isEqualTo("CONSUMED");
        assertThat(jdbc.queryForObject(
                        "SELECT COUNT(*) FROM case_execution_command WHERE case_id=?", Integer.class, control))
                .isEqualTo(1);
        Map<String, Object> result = new LinkedHashMap<>();
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
        assertThat(consumption
                        .consume(new AuthorizationRepository.DispatchCandidate(authorization, caseId))
                        .dispatched())
                .isTrue();
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
        record(
                "consume-wins-" + repetition.getCurrentRepetition(),
                Map.of(
                        "scenario",
                        "consume-wins",
                        "trial",
                        repetition.getCurrentRepetition(),
                        "update_rejected",
                        true));
    }

    private void rejectApproval(String caseId, String authorization) {
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
