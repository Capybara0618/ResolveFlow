# 新评测体系实施与验证

2026-10-05。按用户最新要求完成评测工程，不优化生产Agent/上下文/RAG。范围见[规格](../docs/agent-evaluation-rebuild.md)，操作见[使用指南](../docs/evaluation-guide.md)。活动数据全部在[evals/current](../evals/current/README.md)，历史成绩不计新分数。

## 交付

| 批次 | 已交付 |
| --- | --- |
| 1 数据协议与清理 | 唯一活动目录、版本/hash、嵌套Gold隔离、主体/配对/分组/标注检查、旧15文件先备份后移除 |
| 2 政策语料 | 三商家×两个不可变合成版本，共六bundle/54规则；业务条件、例外与材料要求 |
| 3 评测样本 | 60检索查询（54正例/6无适用政策）、32Agent案例/16对、20Harness+8上下文检查；答案独立 |
| 4 执行与评分 | eval.ps1、随机隔离PG、真实本地embedding/索引、真实MCP stdio/合成localhost源、生产AgentScope循环、调用记录/中断分母、预算与进程锁 |
| 5 结果和复核 | 冻结试跑、可读摘要、相同条件对照、离线重判、hash绑定人工复核、五当前版本持久回放包、操作及限制文档 |

所有数据为SYNTHETIC，Gold状态`policy_checked_by_codex_not_human`。尚无用户/独立专家Gold审查。未发货/丢失为dev，签收争议/质量核验为test；同对同诉求/主体、权威事实不同。家族隔离不是随机商业分布。没有新增生产工具、改模型prompt、调检索、迁移业务库或重算日常工单。

## 集中验证

- 数据/评分/预算/比较/人审及真实MCP执行器测试：**84通过、0失败、0跳过**。覆盖冻结文件/漏Gold、跨店policy、缺/同答案、假hash/政策版本、全转人工不能通过明确退款、金额/次数/未知调用保护、并发预算锁、不同分母/评分/模型/embedding拒绝对照、报告不可覆写、零网络离线重判及待人审不能算完成。
- 回放/导出/网络隔离、SDK持久恢复、旧fence/worker恢复、政策索引关联测试：**60通过、0失败、0跳过**。其中本轮单独回放相关16通过，全部包含在最终60中，不能重复加总为76。两个组共144项。
- 独立命令`harness`：**28/28通过**；`replay`：**5/5 MATCH**；`validate`：三商家/六bundle/32case/16pair/60query。无零步骤成功。
- Ruff check/format、PowerShell语法、Git差异检查通过；生产`agent/src` diff为空。不是全Java/网页回归，本轮未运行它们。
- 真实MCP测试发现“多余line_id参数直接进server会被忽略”，没有假称协议本身拒绝。测试确认返回仍是绑定行、无法跨主体；生产ActionGate另有拒绝该参数的检查，run不匹配也拒绝。

实际主要命令（项目根目录，关联PG组使用`RESOLVEFLOW_AGENT_DB=postgresql://agent:agent@127.0.0.1:55433/agent_db`；依赖沿用锁）：

```powershell
agent/.venv/Scripts/python.exe -m pytest agent/tests/unit/test_current_evaluation_dataset.py agent/tests/unit/test_h1_pairs_dataset.py agent/tests/unit/test_current_harness_checks.py agent/tests/unit/test_evaluation_scoring.py agent/tests/unit/test_evaluation_controls.py agent/tests/unit/test_evaluation_review.py agent/tests/integration/test_current_evaluation_mcp.py -q --tb=short

# 下述60项当时在agent目录执行，相同文件换成根目录路径如下：
agent/.venv/Scripts/python.exe -m pytest agent/tests/integration/test_replay_golden.py agent/tests/unit/test_replay_pack.py agent/tests/integration/test_strict_replay.py agent/tests/integration/test_replay_export.py agent/tests/integration/test_replay_container_isolation.py agent/tests/integration/test_sdk_durable_recovery.py agent/tests/integration/test_c09_legacy_fence.py agent/tests/integration/test_recoverable_worker.py agent/tests/integration/test_policy_index.py -q --tb=short

./eval.ps1
./eval.ps1 -Mode harness -Output reports/current-evaluation/harness-final.json
./eval.ps1 -Mode replay -Output reports/current-evaluation/replay-final.json
./eval.ps1 -Mode rag -Output reports/current-evaluation/rag-final.json
./eval.ps1 -Mode mock -Output reports/current-evaluation/mock-final.json
agent/.venv/Scripts/python.exe scripts/policy_search_eval.py --skip-dense --report reports/current-evaluation/bm25-compat-final.json
```

这些文件已存在，复跑应使用新的Output，不能覆写证据。脚本模型完整运行返回1，因为被测案例未完成；RAG/Harness/Replay返回0。

## 实际基线，不是质量提升

| 路径/场景 | 实际结果 | 证据 |
| --- | --- | --- |
| 真实dense/54正例 | 覆盖@1 79.63%，@2 91.67%，@5 97.22%；全依据@5 52/54；主体/版本违规0 | [检索摘要](current-evaluation/rag-summary.md)、[逐查询JSON](current-evaluation/rag-final.json) |
| BM25/54正例 | 覆盖@1 62.04%，@2 76.85%，@5 92.59%；全依据@5 49/54；违规0 | 同上；[兼容入口](current-evaluation/bm25-compat-final.json)同分数 |
| 无适用政策/6负例 | dense和BM25均返回候选6/6；不混入正例覆盖率 | 候选存在不等于退款适用，未宣称“无误判” |
| 完整脚本SDK/32例 | 联合达标0/32；未完成32/32，全部CONTEXT_REQUIRED_OVERFLOW；92次脚本调用 | [摘要](current-evaluation/mock-current-summary.md)、[原始执行](current-evaluation/mock-final.json)、[当前评分](current-evaluation/mock-scored-current.json) |
| 有限真实DeepSeek/8个dev例 | 联合达标0/8；动作匹配4/8；未完成3；21模型调用；完整4对均未联合达标 | [摘要](current-evaluation/live-current-summary.md)、[原始执行](current-evaluation/live-baseline.json)、[当前评分](current-evaluation/live-scored-current.json) |
| 人审 | 0/8已评、8待复核，review-score返回1 | [待填表](current-evaluation/review-pending.json)、[判分](current-evaluation/review-pending-score.json) |
| 对照入口 | 同32案例报告自比，改进0、退化0 | [自比记录](current-evaluation/comparison-current-smoke.json)，不是优化前后实验 |

真实模型8例均在用户进一步收敛“只构建体系”前执行完成；之后无新付费调用。准确usage21/21：输入25546、输出5421 tokens，共30967。累计请求预算21/96、保守美元预留0.0610104；预留不是实际账单。按[官方价格](https://api-docs.deepseek.com/quick_start/pricing/)峰时非缓存0.30/1.20美元每百万输入/输出估算，已知tokens费用上界约0.014169美元，缓存/时段实际结算未查询，不能当实付金额。模型请求名及返回别名均deepseek-flash，本地client固定thinking disabled/JSON/temp0。

生产prompt及来源/必保留事实在本合成源场景超过上下文保护预算，完整脚本因此失败；有限Live另有ACTION_REFUSED、CROSS_SCOPE_CITATION及过早提问/缺订单调查。终态违规动作0只表示最终记录的终态计数，不代表模型从未尝试非法行动。没有为了高分绕过预算、删来源、改Gold或降低安全检查。

## 清理与保留

[机器清单](current-evaluation/cleanup.json)列15个退役文件的sha256。先复制到本机忽略目录`tmp/evaluation-legacy-20261004-231202`再核对仓库内绝对路径并移除；5新replay包使用当前生产SDK导出并保留缺工具/改请求/unsupported断言。旧失败报告仍在历史，不把更换数据当修复生产代码。

旧`policy_search_eval.py --report`现转发当前60查询，`--skip-dense`明确只测BM25；旧verify脚本内历史步骤名policy-retrieval-40保留为原作者未提交改动，实际样本数量以新报告为准，不再读已移除的40条查询。旧H1三个测试仍检查新数据泄漏/同主体差事实/Gold区分，详细故障变异另在新测试，未跳过旧安全意图。

本轮只写随机eval_*和测试t_* schema，最后不存在遗留eval_*。日常public Agent仍4 COMPLETED / 15模型调用 / 10工具调用 / 8回调，与任务前记录相同；无Java业务写入口、审批、退款、public Agent写入或日常队列消费。没有声称本轮重新计算全部MySQL表hash。

Docker中途停止导致BM25兼容命令ConnectionTimeout，此次不算通过；用户恢复Docker后，只恢复现有本项目PG容器并重跑成功，没有启动业务队列/模型worker、删卷或重建业务数据。其他作者原四个工程/verify/Commerce测试改动和历史草图/日志保留，不夹带提交。

## 失败修正与边界

初版数据测试4失败/4通过，生成并修正订单主体后8通过；后续新增完整性/主体检查都已通过。预算单测初版Msg位置/字符串参数不符合锁定AgentScope 2.0.8接口，改为实际TextBlock；MCP断言修正为实测的绑定行行为；离线重判strict enum改用model_validate_json。初版仅生成报告返回0的Agent入口改为评分失败返回1，逐轮持久化和计划分母补齐。错写不存在test路径曾零测试返回1，最终使用存在的回放模块执行通过。Ruff长行/导入和文档换行已修正，不通过删断言/跳过解决。新增Windows报告保留CRLF以保持原报告hash；默认Git将CR误报行尾空白，最终用`git -c core.whitespace=blank-at-eol,blank-at-eof,space-before-tab,cr-at-eol diff --cached --check`识别合法CRLF并检查实际空白问题，未修改全局配置或改写冻结证据。

当前工程可重复运行并发现失败，不能说Agent效果已可靠：Gold未经独立人审；解释/提问语义人工评分待做；完整32例Live及test Live未跑；没有真正优化前后LLM对照；质量Gold要求物流额外读取，是严格合成调查来源约定，尚未覆盖所有等价证据路径；没有允许REJECT的正例，拒绝当前主要测错误拒绝防护。三店合成材料接口与Java内部evidence引用协议不同，不是Java整链验收；八上下文组件检查使用简化system，不保证完整生产prompt不溢出；五回放包为显式mock合成持久轨迹，不支持宣称Live轨迹已严格回放。

这些限制均留给后续由用户主导的数据审查或优化。本轮交付到此，不自动开启下一优化任务或新付费评测。
