# C05.2b-3b 交接（2026-09-23）

给新会话读的一份自足交接。**先读 `tasks/todo.md` 里 C05.2b-3a / C05.2b-3b 两段**（逐片先红后绿、
断言内容与理由都记在那里），本文件只讲"现在站在哪、下一步做什么、哪些坑会误导判断"。

---

## 1. 一句话位置

**C05.2b-3b（Case 侧结果投影）已完成并推送。** 远端 `main` = `b814463`，本地工作树干净。
下一件事：**C05.2c** —— case 侧 RocketMQ 结果监听器接线 + 真实 broker 上的两段端到端。

## 2. 已验证的事实（可以作为前提，不要重新论证）

- case-service 全量 **177 条：0 失败 0 错误 1 skipped**（跳过的是 env-gated 的真实 broker
  `CoreEventTransportSystemTest`）；`spotless:check` 干净。Commerce 68/68、shared-kernel 58/58
  （本轮未改动，沿用上一轮验证）。
- 三种结算结局都能落到正确状态，且**与结果认领同一事务**（`docs/core-contracts.md:86`）：
  - `SUCCEEDED → CLOSED_SUCCESS`（timeline kind `CASE_CLOSED`）
  - `FAILED → PENDING_REVIEW`（`EXECUTION_UPDATED`，detail 带 `reason_code`）
  - `UNKNOWN → RECONCILING`（`EXECUTION_UPDATED`，不关单、不释放、输入继续冻结）
- 定序：只有**严格更高**的 `aggregate_version` 能推进工单。迟到者仍追加一行 `EXECUTION_UPDATED`，
  detail 带 `ignored_as_stale: true` 与 `superseded_by_version`；`case_status` 记的是**工单保持的**状态。
- 并发安全（切片⑤ 用一条并发测试换来三个真缺陷的修复）：
  1. **工单行锁先于 inbox 认领**（`cases.findCaseForUpdate`）——否则两事务锁顺序相反会死锁；
  2. **轨迹序号分配走加锁读**（`highestSequenceForUpdate`）——`SELECT MAX(sequence)` 在 REPEATABLE READ
     下是快照读，会撞 `case_timeline.PRIMARY`；`highestSequence` 保持不加锁留给读路径；
  3. **陈旧行恒用 `EXECUTION_UPDATED`**——用目标状态的 kind 会把一条被忽略的旧成功写成 `CASE_CLOSED`；
     同批把 `highestAppliedVersion` 改为加锁读，否则等锁的事务会从快照里读到"还没有已应用行"而重复应用。
- **全程没有新增状态、timeline kind、列或迁移**（V13/V14 之后没有 V15）。这不是省事：V2 的
  `chk_timeline_kind` 与 `CaseStatus` 的 CHECK 已经把需要的词汇钉住了，复用它们是刻意选择。

## 3. 关键文件

| 作用 | 路径 |
| --- | --- |
| 结果消费与投影 | `java/case-service/src/main/java/com/resolveflow/caseservice/result/CaseResultConsumer.java` |
| 结果 inbox | `.../result/CaseResultInboxRepository.java`、`.../result/CaseResultTrustConfiguration.java`、`.../result/CaseResultVerifier.java`、`.../result/CaseResultRejectionLog.java` |
| 工单状态与轨迹 | `.../casefile/CaseRepository.java`（`transition`/`insertTimeline`/`highestSequence*`/`findCaseForUpdate`）、`.../casefile/CaseStatus.java` |
| 迁移 | `.../resources/db/migration/V13__case_result_inbox.sql`、`V14__case_result_inbox_deliveries.sql`（只追加，不得改已执行迁移） |
| 测试 | `java/case-service/src/test/java/com/resolveflow/caseservice/casefile/CaseResultConsumerApiTest.java`（14 条，含并发那条） |
| 账本 | `tasks/todo.md`（C05.2a / C05.2b-1 / b-2 / b-3a / b-3a 审查修复 / b-3b 各片） |
| 证据 | `reports/c052b3a-result-inbox/`、`reports/c052b3b-projection/`（每片一份红跑 + 全量绿跑） |

## 4. 命令（环境已配好，照抄即可）

```powershell
Set-Location "E:\Code+Agent+Backend"
$env:JAVA_HOME="C:\Users\hjn\.jdks\jdk-21.0.12.1+1"
java\mvnw.cmd -f java/pom.xml -B -ntp -pl case-service -am test          # 全量 case-service
java\mvnw.cmd -f java/pom.xml -B -ntp -q spotless:check                  # 必须 exit 0
pwsh -File scripts/verify.ps1 -Suite all-offline                         # 项目门禁
```

- 单测：`"...-Dtest=类名#方法名" "-Dsurefire.failIfNoSpecifiedTests=false"`（引号必需）。
- `-am` 必需；日志一律 `Tee-Object` 落盘再读文件——**管道退出码不可信**。
- 先红后绿：红跑与绿跑日志要用**不同文件名**（这条踩过坑）。

## 5. 下一件事：C05.2c（建议做法）

1. **case 侧结果监听器**：镜像 C05.1b 消费端的形状（见 `java/commerce-service/.../messaging/` 的
   `RocketMqResultPublisher` 与 case 侧侧对称物），把收到的消息交给**已验的**
   `CaseResultConsumer.consume(...)`。topic 是 `rf.case.core.v2`（broker 名走 `CoreTopicNames.brokerName`），
   消费组另行命名，不要复用 commerce 的组。
   **当前只有服务方法、没有监听器**——所以真实部署里结果不会自己到达，这是整条链最后一段缺口。
2. **两段 e2e**：approve → command（`rf.commerce.core.v2`）→ refund → result（`rf.case.core.v2`）；
   显式打开 dispatch/delivery 循环（`resolveflow.events.outbox.delivery-enabled` 一类开关），
   用真实 RocketMQ（Testcontainers 或本地 broker）。
3. **未决问题**（从 b-3a 起就挂着，别忘）：**业务拒绝怎么回传 Case**。

## 6. 未清的审查待办（不阻塞 C05.2c，但不要丢）

1. `amount_minor` 缺前置校验：目前只有 DB CHECK，违反时是 `DataIntegrityViolationException`，
   且**不留拒签行**（与下面第 3 条同类）。
2. `CaseResultVerifier.direction(...)` 靠**消息文本**区分 `WRONG_DIRECTION` / `BAD_SIGNATURE`
   （`message.contains("does not come from")`）——`CoreEnvelope` 措辞一改就错分类；要改就与 commerce 的
   `EventVerifier` **一起**改，否则两侧不对称。
3. 未知 `state` 的拒签路径**没有测试**：需要新的夹具方法造出"事件类型与载荷状态不一致"的文档
   （现有夹具是用 state 反推 event_type 的，造不出来）。
4. b-3a 遗留：`case_result_rejection` 表是子代理超出简报引入的设计选择（已记录，未回退）。
5. 路由数口径矛盾未解：子代理写 "Case 18 / Commerce 5 / Agent 5 = 28"，C05.2a 记录写
   "Case 18 / Commerce 4 / Agent 5 = 27"，账本标为**待核对**（grep 没找到钉住它的测试）。

## 7. 会误导判断的环境事实

- `smoke-agent-service` 每轮 0.1s PASS：8090 一直被**外部 PID 25796**（python，2026-09-23 10:37 启动）占用
  → 这一项**不算**"agent 服务可启动"的证据，报告里要注明。
- **工作区不可靠**（本轮发生过两次静默回退）→ 验证过的提交要推送，证据放 `reports/`。
- 推送偶发 `schannel: failed to receive handshake, SSL/TLS connection failed`，**重试即可成功**。
- `git commit -m` 里带中文引号会被 PowerShell 当引号解析 → 提交信息避免特殊引号。
- `spotless:apply` 会重排代码：刚跑过 spotless 后再编辑，必须先重读文件（否则报 "file changed since it was read"）。
- 一条流程教训：子代理交付的东西必须由父级独立复核（b-3a 那次，子代理把一次**没跑过的**全量绿
  写进了账本，且留下一个真 bug —— 见账本"父级复核"段）。

## 8. 推送与提交轨迹

远端 `main` = `b814463`（C05.2b-3b 切片①–⑤）。本会话本轮推送的链：

```
5649567  C05.2b-3a（子代理实现，父级独立复核 170/170 并更正其全量绿引用错误）
97f1b8a  C05.2b-3a 审查修复：第三次投递被当成新认领 -> V14 deliveries
f9f4aa9  C05.2b-3b 约束侦察与计划（未写代码）
96b7967  C05.2b-3b 切片① 先红（证据入库；红测试故意未提交）
f08d9d9  C05.2b-3b 切片①：成功 -> CLOSED_SUCCESS
0a6c3f5  C05.2b-3b 切片②：确定失败 -> PENDING_REVIEW
50c554f  C05.2b-3b 切片③：UNKNOWN -> RECONCILING
6613fd6  C05.2b-3b 切片④：按 aggregate_version 定序
b814463  C05.2b-3b 切片⑤：并发测试 + 三个真缺陷修复
```

AGENTS.md 的规矩照旧：**不擅自推送**、不清库删卷、迁移只追加、不为通过而删断言、真实记录日期/文件/
命令/结果/失败与未运行项。