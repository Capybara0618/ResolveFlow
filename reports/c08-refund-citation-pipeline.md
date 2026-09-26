# C08 通过型退款：真实引用进入模型输入与出站（2026-09-26）

## 问题与实现

前置 `c77f3f4` 已修最终方案验证/出站引用与worker事务，并推送确认。
本步继续核查真实MCP工具observation与PG政策检索命中能否共同形成退款候选。
新增 factory 集成用例驱动 queue → factory → AgentScope SDK → worker → outbox：

- 模型脚本先选物流读取，再选固定政策检索，最后从真实返回的 observation/hit 复制引用。
- 工具走官方 MCP stdio 子进程，HTTP 上游为本地合成测试桩；政策索引与 outbox 用真实 PG 的隔离测试 schema。
- embedding 为确定性 stub，模型为 mock；不是 live 模型、真实 Java、真实物流或退款执行证明。
- 出站引用逐成员等于最终候选，且引用的 id/hash 必须出现在模型实际 messages 中；不只检查 mock 隐藏 context。

首次运行 **1 failed / 7 passed**，失败在真实 messages 缺证据 `content_hash`。
虽然候选借 mock context 成功提交，但正式 P3 只渲染工具 result，未给模型 envelope 的版本/hash/id，
此前的通过只能说明脚本能访问隐藏数据。

修复 `harness/context.py` 的 P3：在有界 result 前独立渲染引用元数据，直接取 observation envelope，
不从 result 提取；仅成功且同时有 version/hash 时携带二者。无元数据不补造。
独立头不改 `READ_OBSERVATION` 的原文/offset，截断与整体输入预算仍走既有检查。
`context_policy_version` 升为 `p0-p4-v2-citation-metadata`，使新 manifest 明确区分上下文策略；
不重写旧run/manifest，不改锁、动作ABI、预算或数据库迁移。

## 实际验证

工作目录 `E:/Code/Agent+Backend/agent`，使用现有 `.venv`：

- `.\.venv\Scripts\python.exe -m pytest tests/unit/test_context_builder.py -q -p no:cacheprovider --tb=short`
  → RED **2 failed / 22 passed**（缺引用头）；新增断言还验证 result 自带伪造hash/版本不能覆盖可信元数据。
- P3修复后，ContextBuilder + deployment factory 两文件 → **32 passed**。
- 最终策略版本更新后，`.\.venv\Scripts\python.exe -m pytest tests/unit/test_harness_manifest.py tests/unit/test_context_builder.py tests/integration/test_deployment_factory.py -q -p no:cacheprovider --tb=short`
  → **40 passed**。
- `.\.venv\Scripts\python.exe -m ruff check src tests` → **All checks passed**；首次仅报一处121字符行，已换行并复核。
- `.\.venv\Scripts\python.exe -m pytest tests -q -p no:cacheprovider --tb=short` → **1030 passed / 9 skipped / 1 warning，139.34秒**。
  全量启动后仅调整context策略版本常量，其最终版本由上方40例另验；warning为既有Starlette/AnyIO弃用提示。
- `.\.venv\Scripts\python.exe -m mypy` → **9 errors in 4 files (checked 52 source files)**，仍是前步相同的既有 `no-any-return`，本步模块无新增错误。
- 根目录 `git diff --check` 及本步文档本地Markdown链接检查 → 通过。

未运行：Java/Spotless、all-offline、真实Java业务闭环、真实embedding质量实验、live/H1–H5、C09/C10。
这一步不代表 Java 接受或退款成功，不勾 C08.1/C08.2 完成。下一步为常驻worker装配入口的独立小步，
按当前工厂的显式mock/live模式与生命周期接入，不制造默认脚本，不新增收费调用。
