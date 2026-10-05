# 第一批完成记录：输入、评分与上下文诊断

2026-10-05。执行范围按[第一批规格](../../docs/agent-evaluation-alignment.md)。本批完成校准与诊断，不宣称 Agent 建议质量改善。

## 交付

- 新 `evals/aligned-v2` 与默认 `eval.ps1` 入口；真实派发材料快照与材料引用查询分开，合成派发经过生产 `RunRequest` 验证。三店六政策版本、32 案例/16 对、60 RAG 查询保留；v1 与旧报告未修改。
- 质量退款允许订单送达投影替代重复物流读取；正例评分增加精确主体、付款/占用/履约事实与注册人工结论检查。允许/禁止动作和政策 Gold 未改，假引用、未确认、更新后失效的核验不会通过。
- 检索候选统计取本次实际 Observation；上下文超限有分层大小、cap 与累计预算诊断，没有删事实或放宽预算。
- 五个新持久回放包、独立 replay manifest 与 strict 检查；旧回放不覆盖，不给旧 run 换 manifest。

## 实际结果

| 验证 | 结果 |
|---|---|
| Python 集中回归 | 166 passed，无 skip；涵盖评分/隔离/真实 MCP/上下文/检索/回放/持久恢复/fence |
| 追加来源校验 | 新增 3 项通过；所在文件共 17 passed，已有 14 项不重复计数；不同测试合计 169 |
| Java 原有协议 | ReviewerRunInputTest 1、CaseEvidenceInternalApiTest 5，合计 6 passed，无 skip |
| 独立 Harness / 上下文入口 | [28/28](harness-final.json)，简化检查，不替代完整生产上下文 |
| 当前 strict 回放入口 | [5/5 MATCH](replay-final.json)，缺记录/请求篡改仍明确失败 |
| 实际 dense 轨迹探针 | [2 候选、轨迹 hits=2](search-trace-final.json)，脚本模型，非 LLM 质量评测 |
| 32 案例 SDK＋真实 MCP＋embedding | [全部上下文溢出](mock-aligned-v2.json)，34 次脚本模型调用，执行异常 0、联合通过 0/32 |
| 离线重判 | [0/32](mock-scored-final.json)，新模型调用 0 |
| 数据/定点 Ruff/PowerShell 入口 | v1/v2 hash 校验与命令通过；旧报告必须显式使用对应 Dataset |
| 全项目 mypy | **未通过**：68 源文件检查有 16 错误，位于本批未修改的 9 个文件；没有宣称全项目类型门禁通过 |

脚本模型不是真实 LLM；本批新增付费调用为 0。没有新增真实建议质量或真实 RAG 召回成绩。之前 dense 全依据 52/54、BM25 49/54 与有限 Live 0/8 仍属于原版本报告，不能与本批跨版本相减作为提升。Gold 独立人审、解释语义、人类问题评价、全量 Live、Java 全业务链与网页部署未运行。

## 溢出已经定位

[逐例诊断](diagnostics-summary.json)显示 32 例都在本地保守估算阶段停止：强制输入估算 **7014～8133**，cap **6912**。这是 UTF-8 字节估算触发 Harness 上限，不是证明 DeepSeek 的实际上下文窗口不足。未向 provider 发出被拒绝的请求，也没有账单 token 可作为这些请求的精确计数。

| 内容 | 强制 section 的 UTF-8 字节贡献 |
|---|---:|
| P0 固定部分 | 3558，其中 action/tool schema 2255、system 1303 |
| P1 诉求、快照、已确认动作、读取进展 | 911～1939 |
| P2 精确事实及来源引用 | 1747～2467 |

上述为 section 正文字节，合计不含渲染标签、JSON 转义/消息 framing 和 wrapper allowance；`mandatory_estimate` 才是用于拒绝的完整估算，不能把正文表加总当 provider token。

例如 A13A（质量问题已人工确认），首轮估算 5519 可以发送；读取订单后强制输入估算 7576，超过 6912，其中 P0=3558、P1=1428、P2=1765。订单字段已经读到，但第二轮尚未发出，无法再由模型选择材料查询、政策检索或提出建议。32 案例中 30 个只发出首轮，2 个发出两轮。RAG 此时没有机会参与，不能把这些失败解释为 RAG 返回了 0 个候选。

第二批应优先检查固定 schema、材料/来源的重复表达和字段逐项 provenance 的体积，并审查字节估算与 wrapper 预留的计算方式；保持事实、冲突、例外、引用来源和权限。先让真实输入在原预算内可用，再谈调查策略与召回。此次没有实施上述表达优化。

## 实际命令

所有 Python 命令使用锁定的 `agent/.venv/Scripts/python.exe`。数据库仅用本机 `127.0.0.1:55433/agent_db` 的随机隔离 schema。

```powershell
# 集中回归（对应166 passed）
agent/.venv/Scripts/python.exe -m pytest agent/tests/unit/test_current_evaluation_dataset.py agent/tests/unit/test_evaluation_alignment.py agent/tests/unit/test_evaluation_scoring.py agent/tests/unit/test_evaluation_controls.py agent/tests/unit/test_evaluation_review.py agent/tests/integration/test_current_evaluation_mcp.py agent/tests/integration/test_context_wiring.py agent/tests/integration/test_policy_search_action.py agent/tests/unit/test_context_quality.py agent/tests/integration/test_replay_golden.py agent/tests/unit/test_replay_pack.py agent/tests/integration/test_strict_replay.py agent/tests/integration/test_replay_export.py agent/tests/integration/test_replay_container_isolation.py agent/tests/integration/test_sdk_durable_recovery.py agent/tests/integration/test_c09_legacy_fence.py agent/tests/integration/test_recoverable_worker.py -q --tb=short
agent/.venv/Scripts/python.exe -m pytest agent/tests/unit/test_evaluation_alignment.py -q --tb=short

# JDK21；未修改Java生产代码
./java/mvnw.cmd -f java/pom.xml -B -pl case-service -am '-Dtest=ReviewerRunInputTest,CaseEvidenceInternalApiTest' '-Dsurefire.failIfNoSpecifiedTests=false' test

./eval.ps1 -Mode validate
./eval.ps1 -Mode validate -Dataset evals/current
./eval.ps1 -Mode harness -Output reports/agent-alignment-batch1/harness-final.json
./eval.ps1 -Mode replay -Output reports/agent-alignment-batch1/replay-final.json
agent/.venv/Scripts/python.exe scripts/agent_eval.py mock --output reports/agent-alignment-batch1/mock-aligned-v2.json
./eval.ps1 -Mode rescore -InputReport reports/agent-alignment-batch1/mock-aligned-v2.json -Output reports/agent-alignment-batch1/mock-scored-final.json
agent/.venv/Scripts/python.exe reports/agent-alignment-batch1/search-trace-probe.py reports/agent-alignment-batch1/search-trace-final.json
```

以上 JSON 不可覆盖，复跑须换 Output。32例 mock 退出码为 1，表示联合未达标；不能因程序没有异常就报成功。新 pack 由隔离 PG 下 `test_golden_trajectory` 设置 `RESOLVEFLOW_REPLAY_GOLDEN_DIR` 导出，再 `freeze_replay()` 固定包 hash，不修改原 v1。

初始失败与修复：新增失败测试先有 5 failed/2 passed；SDK 首轮诊断漏导入 canonical_json 导致 NameError（1 failed/46 passed），补导入后通过；Java 参数未完全引用被 PowerShell 拆分导致 Maven 失败，完整引用后 6 项通过；再次导出到已存在目录被安全拒绝（5 failed），将本批开发中的旧包保留在 tmp/alignment-replay-before-import-fix，随后重新导出当前源码的五包，未覆写旧冻结资产。首次 Ruff 未指定 agent 配置且扩大到未修改文件有 47 项，最后按项目配置定点检查通过。

在 agent 目录执行 `./.venv/Scripts/python.exe -m mypy`，68 源文件中有 16 项未解决：provider_stub/__init__.py 3，contracts/reviewer_input.py 1、_schemaio.py 1、fixtures.py 1、core_corpus.py 3，harness/verifier.py 2，runtime/runs.py 1，policies/status.py 1，api/app.py 2。这些九个文件本批没有修改；未运行旧提交的完整类型检查，因此不把“位于未修改文件”冒充独立验证过的旧基线。本批三个生产改动文件未出现类型诊断。没有扩大到模拟退款服务、API 或资金校验的类型清理。初次从 agent 目录使用根目录相对 Python 路径未执行，修正为上述命令后才得到真实结果。

## 数据与交接

最终只读核对 public Agent 仍为 4 COMPLETED / 15 模型调用 / 10 工具调用 / 8 回调；无遗留 eval_* 或 t_* schema，见诊断汇总。不清业务表，不消费日常队列，不审批/退款，不重新部署或给历史 run 换代码版本。没有声称本批重算全部 MySQL 表 hash。

生产语义变化仅为记录修正与溢出诊断，新的 source identity 用于新运行。四个原工程/verify/Commerce 测试文件以及历史草图日志保持原状，不夹带提交。本批提交并正常推送核实后停止写入；第二批须按用户下一步指示开始。
