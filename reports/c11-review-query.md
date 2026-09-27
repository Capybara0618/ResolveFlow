# C11.2 审核队列查询：基线与后续对照（2026-09-27）

## C11.2a 已冻结的读路径

- 路由：`GET /api/v1/review/cases?limit=20&cursor=...`，调用方为审核员/本地操作员工作台，Case 服务的 `ReviewController → ReviewQueueService → CaseRepository.findReviewQueue`。客户角色先被 `CaseStaff.require` 拒绝（403），商家 ID 只从验证过的 token 取，不从请求取。
- 查询固定 `merchant_id`、`status='PENDING_REVIEW'`，按 `(updated_at DESC,case_id DESC)` 稳定 keyset 分页，`LIMIT limit+1` 判断下一页；第二条批量读取这些工单的 requested actions，没有 N+1。更新频率由案件状态、材料或授权变化决定；审核期间会变，故缓存只可做短 TTL 非权威视图。
- 合成数据脚本 [`scripts/c11_review_queue_seed.sql`](../scripts/c11_review_queue_seed.sql) 在**独立** `c11_review_bench` schema 建同结构表，固定 20,000 行、2 商家、4,000 待审（每商家 2,000）。`INSERT IGNORE` 使重跑不重复扩行；未删除/清空 `case_db`、共享 Redis 或任何卷。`created_at` 与 `updated_at` 逆序，专门暴露现有索引是否能支持真实排序；没有删除已有索引或人为加延时。
- 执行：仓库根目录 `Get-Content -Raw scripts/c11_review_queue_seed.sql | docker exec -i resolveflow-mysql-1 mysql -uroot -proot`。结果 20,000 / 4,000 / 2；MySQL 8.4 本机单容器，仅为合成诊断数据。

基线 SQL 为 Mapper 的首页条件（`afterUpdatedAt=null`）及同排序/`LIMIT 21`：

```sql
EXPLAIN ANALYZE
SELECT case_id, merchant_id, line_id, description, status, input_revision, version, updated_at
FROM c11_review_bench.aftersale_case
WHERE merchant_id='M-1001' AND status='PENDING_REVIEW'
  AND (NULL IS NULL OR updated_at < NULL OR (updated_at = NULL AND case_id < NULL))
ORDER BY updated_at DESC, case_id DESC LIMIT 21;
```

实测计划：`idx_case_merchant(merchant_id,status,created_at DESC,case_id)` 命中商家/状态后扫描约 2,000 行，并对 `updated_at DESC,case_id DESC` 作 `Sort`；首页 `actual time=9.62ms`，21 行输出。这个现有索引对过滤有用，但排序键不一致。变更前 `ReviewQueueApiTest` 6/6 通过。单次计划时间不是接口 p95，也不预报最终收益；正式接口性能基线与三条件对照按 C11.2e 入口另存原始样本。

## C11.2b 追加排序索引

新增 Flyway `V18__review_queue_order_index.sql`，在 Case 权威表追加 `(merchant_id,status,updated_at DESC,case_id DESC)`，保留原索引供其他路径使用。相同 20,000 行数据的首页 `EXPLAIN ANALYZE` 从扫描约2,000行+Sort、9.62ms，变为索引顺序读取21行、0.156ms。非首页、同一游标条件 `updated_at<'2026-09-01 02:45:00'` 下，用 `FORCE INDEX` 对照旧/新计划分别为扫描2,000行+Sort、10.1ms，与索引范围读取21行、0.106ms。强制两种索引返回的21个 `(case_id,updated_at)` 顺序及内容完全一致，首/末 ID 为 `...9895`/`...9795`。这些是一次性、未隔离资源波动的 SQL 诊断，不当作最终接口吞吐收益。

追加迁移在临时 MySQL 的 `ReviewQueueApiTest` 中验证权限、稳定排序、游标分页与跨主体拒绝，**变更后 6/6 通过**；Flyway 实际应用到版本18。

## C11.2c 非权威 Redis 页缓存

`ReviewQueueService` 在验证 staff 身份、limit 和游标后才查缓存；`RedisReviewQueueCache` 只存审核列表的 `items/nextCursor/limit`，Key 包含独立 namespace、已验证 token 的 merchant、limit 和游标 SHA-256。TTL 为 2 秒，无主动跨实例失效；案件更新后最多可能在该窗口看到旧列表，审批仍由 Case 数据库和 `If-Match` 版本验证，退款金额/授权/Agent 证据不读此缓存。默认关闭，core Compose 明确开启。实 Redis 测试覆盖命中、未命中、主体与游标隔离、覆盖更新和过期；模拟缓存命中不查库，客户身份在缓存前拒绝。

## C11.2d 有界回源与故障

Redis connect/command timeout 都配置为 100ms；缓存读/写异常只影响列表读性能。启用缓存时，每个 Case 实例用公平信号量限定同时最多 8 个回源，等待最多 100ms，超限返回可重试的 HTTP 503 `SERVICE_UNAVAILABLE`；不持有数据库事务等待 Redis。计数器记录 hit/miss/error、真实 Mapper 查询数及拒绝数，`/actuator/metrics` 只在 Case 内部端口暴露，Redis health 不参与核心健康结论。

`RedisReviewQueueCacheIntegrationTest` 使用 Testcontainers Redis 7.4 真实适配器：断连抛错在 2 秒内，`CLIENT PAUSE 1000` 下 100ms 命令超时，实际 `ReviewQueueService` 回源并记录 error/数据库查询；同一真实 Redis 热 Key 过期后 12 个并发读中 8 个回源、4 个拒绝，数据库查询计数为 8。`ReviewQueueBackpressureTest` 另用故障注入和阻塞数据库验证峰值、等待上限及释放后可再读；异常映射测试确认 503/`retryable=true`。该单机守卫不声称跨实例总量上限。

## C11.2e HTTP 小规模试跑

入口：`$env:JAVA_HOME=...; pwsh -File scripts/c11_review_benchmark.ps1 -Seed 42 -Trial`。同等 Bash 入口 `bash scripts/c11_review_benchmark.sh 42 trial` 已语法检查，未在 Linux 实跑。脚本只操作独立 `c11_review_load` schema，Flyway 建完整 Case 表，固定 20,000 工单/4,000 待审、2 商家；**不清理**用户 schema/卷，也不 `FLUSHALL`。三条件依次为保留原合理索引且关闭缓存、追加 V18 索引但关闭缓存、同索引并开启 2 秒 Redis 缓存。每条件 10/30 并发、2 秒预热、5 秒稳态、各重复 2 次；这只是测量入口试跑，C12 才按规格冻结 30/60 秒。固定请求分布为 80% 商家一首页、10% 其下一页、10% 商家二首页；在负载前验证客户 403、两商家隔离、分页无重复，负载中逐响应校验预期 ID，错误请求仍纳入分母。

原始逐请求样本、各窗口指标差值与哈希在 [`reports/c11-performance/20260927-100355/`](c11-performance/20260927-100355/)；三个 `*.json.gz` 可解压为 JSON。Docker Desktop 32 vCPU、7,948,337,152 字节可用内存，MySQL 8.4/Redis 7.4，本机 Windows；同一次试跑内同一 MySQL 数据/Case jar/并发设置，服务逐条件重启。冷页在前置权限/分页校验后等待 2.5 秒，超过 2 秒 TTL，再单独记录；不清共享 Redis。无独立资源隔离、条件顺序随机化或长稳态，因此结果只说明小样本趋势。

| 并发 | 条件 | 成功 RPS 两轮 | 成功 p50 ms 两轮 | 成功 p95 ms 两轮 | 错误率 | 实际 DB 查询/成功请求 | 缓存命中率 |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| 10 | 原索引基线 | 443 / 454 | 21.05 / 20.62 | 35.43 / 34.73 | 0 / 0 | 2 / 2 | 不适用 |
| 10 | 追加索引，缓存关 | 866 / 1376 | 11.21 / 6.36 | 17.48 / 12.60 | 0 / 0 | 2 / 2 | 不适用 |
| 10 | 追加索引，缓存开 | 1193 / 1757 | 8.03 / 5.24 | 12.35 / 8.39 | 0 / 0 | 62/5965、54/8787 | 5934/5965、8760/8787 |
| 30 | 原索引基线 | 684 / 674 | 42.75 / 43.10 | 58.65 / 60.02 | 0 / 0 | 2 / 2 | 不适用 |
| 30 | 追加索引，缓存关 | 1607 / 1579 | 18.01 / 18.33 | 26.40 / 27.30 | 0 / 0 | 2 / 2 | 不适用 |
| 30 | 追加索引，缓存开 | 1792 / 1754 | 16.26 / 16.53 | 24.36 / 25.32 | 0 / 0 | 80/8961、112/8771 | 8921/8961、8715/8771 |

缓存 miss 数在上述四轮分别为 31、27、40、56；hit+miss 与成功请求数相同，故障/拒绝均 0。数据库查询计数来自 Mapper 调用处的实际计数，不用 miss 数倒推。10 并发缓存吞吐两轮均高于仅索引；30 并发也较高但增量小，短时试跑不能证明稳定提升。索引条件首轮 10 并发与次轮差距明显，也提示 JVM 预热或资源波动仍有影响。冷页单独记录在 raw `cold`，不与稳态合算。数据库故障/Redis 故障的拒绝测试在上一节，未混入正常窗口。
