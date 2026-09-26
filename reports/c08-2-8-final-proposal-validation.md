# C08.2-8 出站引用与最终方案验证（2026-09-26）

## 问题与结果

接管源码 `42707d7`，用户确认 DSH 已停止；接管记录提交 `215b1f9` 已正常推送并用远端 SHA 核对。
沿用 AgentScope 2.0.8 与现有锁，不重选架构。本步只修 Python worker 出站边界：

- `callback_payload` 将候选的 `evidence_refs`、`policy_refs` 按现有核心类型序列化，保留来源、版本和 hash。
- `RunWorker.finish` 组装最终 body 后，用当前 run 的 observations 和派发钉住的 bundle 集合调用 `verify_proposal`。
- 验证失败不入 PROPOSAL outbox；使用首个稳定拒绝理由将结果标为未完成，并在同事务写 FAILED 状态与失败回调。
  被拒候选保留在返回结果中，不将模型输出伪装成合法方案。缺 summary 由冻结 Schema 拒绝，不新增 ABI 强制或改 prompt hash。
- 原有 RUNNING 条件更新仍生效；取消/失效状态不被覆盖。验证无外部调用，放在写事务之前。
  回滚反例发现原有连接池为 autocommit、worker未开显式事务，故 claim/finish 都补 `connection.transaction()`，
  真正让状态与回调同事务，并使 claim 的行锁保持到事务结束；没有改变全局连接池行为。

Python 验证通过仍不等于 Java 接受、审批或退款成功。

## 测试与实际失败

工作目录 `E:/Code/Agent+Backend/agent`，使用现有 `.venv`：

1. 接管最小基线：
   `.\.venv\Scripts\python.exe -m pytest tests/unit/test_callback_payloads_match_the_case_contract.py tests/unit/test_proposal_verifier.py tests/integration/test_run_worker.py -q -p no:cacheprovider --tb=short`
   → **30 passed**。
2. RED：在真实 PG 的每测试隔离 schema 中增强成功退款 fixture（工具 observation + 政策检索命中），新增六类拒绝反例。
   首次 fixture 错用了字符串 `source_type`，10例因 Pydantic 严格枚举验证失败；改为既有枚举后，**7 failed / 10 passed**：
   成功方案缺出站引用；缺 summary、无引用、hash 篡改、不可见引用、跨 bundle、退款同时缺证仍投递 PROPOSAL。
3. GREEN：接入后，先校正 fixture 的政策 observation 工具名为既有 `POLICY_SEARCH_TOOL_NAME`；退款同时缺证先被 Schema 拒绝，
   因此预期理由为 `PROPOSAL_SCHEMA_REFUSED`，没有放宽契约。聚焦三文件 → **36 passed**。
4. 追加两例事务反例：模拟合法/非法候选最终 outbox 写入失败，检查 run 状态回滚为 RUNNING，仅保留 claim 的 STARTED。
   成功退款出站同时交给发布的 Case `ProposalPayload` component 校验，避免仅依赖另一份本地形状。
   **真实失败**：首次全量回归 **2 failed / 1024 passed / 9 skipped**（141.26秒），这两例都发现状态已经独立提交。
   `Database.connection()` 的连接池明确设置 autocommit，不能将 connection 上下文当事务。修复 claim/finish 显式事务，
   并补 claim 的 STARTED outbox 失败反例；相关五文件回归（再含 deployment factory 与 supersede）→ **53 passed**。
5. `.\.venv\Scripts\python.exe -m ruff check src tests` → **All checks passed**（此前仅修复一处测试 import 排序）。
6. `.\.venv\Scripts\python.exe -m mypy` → **9 errors in 4 files (checked 52 source files)**，均为既有
   `provider_stub`、`contracts/_schemaio.py`、`contracts/fixtures.py`、`contracts/core_corpus.py` 的 `no-any-return`；worker无新增错误。

7. 修复后最终全量：`.\.venv\Scripts\python.exe -m pytest tests -q -p no:cacheprovider --tb=short`
   → **1027 passed / 9 skipped / 1 warning，136.14秒**；warning为Starlette引用弃用的AnyIO别名。
   strict mypy再次确认仍为上述9个既有错误。9个skipped不当作通过。
8. 根目录 `git diff --check` 与本步文档本地Markdown链接存在性检查 → 通过。

## 边界与下一步

本步调查使用 stub 与合成 observation，PG 与 outbox 事务真实；没有运行真实 Java/MCP/模型调用。
未跑 Java/Spotless、all-offline、跨服务业务闭环、live/H1–H5、C09/C10；Java、依赖、数据库迁移和 ABI 未改。
不勾 C08.1/C08.2 完成。遗留 SQLite 快照原处保留且不提交。

下一小步先核验现有 factory/SDK 的通过型退款用例是否覆盖真实工具 observation 和政策检索命中，再补缺口；
常驻 worker 装配与 Java 复核/审批→退款随后独立验收。C09预算冲突仍未解决，不静默扩额。
