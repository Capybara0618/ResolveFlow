# 第二批：紧凑上下文与多轮压缩

2026-10-05，按用户最新授权完成 Context Engineering。沿用 aligned-v2 的输入、政策、RAG 查询和 Gold；没有新付费 LLM 调用，没有清库、部署 worker 或重算日常建议。

## 结果

| 验证 | 实际结果 |
| --- | --- |
| 完整 SDK / 隔离 PG / MCP / 本地真实 embedding，脚本模型 | 32/32 自动联合检查通过，148 次脚本模型调用，0 异常、0 溢出、0 禁止动作 |
| 上下文 / 引用 / 模型输入 / 恢复 / 预算 / 严格回放 / 评测控制 | 320 passed，0 failed，0 skipped，见 tests-final.xml |
| 独立 Harness | 28/28，见 harness-final.json |
| 当前代码的五个持久回放 | 5/5 MATCH，见 replay-final.json；新资产 evals/replay/context-v3 |
| v1 / aligned-v2 冻结资产校验 | 两套均通过；manifest SHA 与第一批一致 |
| 改动文件 Ruff / PowerShell 解析 / staged diff | 通过；全项目 mypy 仍有原有 16 错误，详见 mypy-final.txt |
| 日常 Agent 数据 | 4 COMPLETED / 15 模型 / 10 工具 / 8 回调，与第一批一致；无遗留隔离 schema，见 database-final.json |

自动评分使用与第一批一致的评分/数据代码，通过 compare.json 核对。**这是流程与安全检查的脚本验证，不是 LLM 准确率。** 评测器本批另修复 DAMAGE→DAMAGED 的枚举错误，因此不能把全部结果变化单独归因于上下文压缩。

同 32 个输入的首轮完整请求 ESTIMATED UTF-8 字节合计 172159→124639，约减少 27.6%；改后首轮 3483～4591。所有实际模型请求均在 cap 内，最大一步估计7167，cap7168。完整调查的累计输入 185778→867646、调用34→148：旧基线早停，新链路走完，不能宣称累计费用下降。复算脚本为 measure.py，详细结果 measurements.json；字节估计不是供应商 token 或计费证明。

## 最终行为

- 包装预留只算一次：最终序列化消息估计包含256包装预留，默认 cap=8192-1024=7168，单步8192上限/累计预算均保留。
- 固定协议收紧；动作字段、合法枚举、引用格式、读取边界、条件与未知状态仍明确。真实 order_status / 旧 status 映射沿用第一批，未重复迁移。
- 事实按完整来源身份分组，身份展示一次，值、状态、冲突及 protected_fact_hash 不变；政策正文、条件、例外、版本/hash不裁剪。
- 每轮重建必要上下文，沿用最近动作窗口、近期可选片段和旧结果索引。无额外 LLM 摘要，无 SDK 隐藏历史追加；完整原文和真实请求继续保存。
- 正文超过600字符时展示首240/尾120、总长和 material:ID；中段索引记录 omitted_refs。READ_OBSERVATION(offset,limit)从当前run/revision原快照分页读取，未来版本、跨run、改变快照、越界均拒绝。材料窗口保留用户/人工来源，不能代替 get_case_evidence 正式引用。
- 断点恢复复用落库模型/工具结果与原预算，材料原文从持久 review_context 重建；三种中断窗口通过。严格回放限定扩展到记录完整的 READ_OBSERVATION，本地页直接复用记录、不调用网络；缺记录、篡改、参数不一致仍失败。政策搜索回放仍在原 UNSUPPORTED 子集外。
- 新 context/计量版本写入 manifest。旧 aligned-v2 包在当前代码下明确 PACK_INVALID，未静默换版本；旧 v1/v2 回放文件未覆盖。

## 实际执行与失败记录

1. 初始4个新失败测试暴露重复包装、重复来源、长文无法读回、未来版本缺校验；实施后通过。旧格式断言改为完整四字段来源断言，裁剪测试仍强制预算不足并检查原事实 hash。
2. 第一轮完整 mock-probe.json：6/32、26溢出、125调用。第二轮 mock-final.json：31/32、1溢出、147调用；进一步删除重复解释及包装后，最终 mock-complete.json：32/32、148调用。所有中间报告保留，没有改 Gold 使其通过。
3. 新材料 strict 测试先遇到显式合成描述门禁，再暴露旧回放器不支持 local read；补合成标识并限定支持 READ_OBSERVATION 后通过，没有放宽网络隔离或导出真实工单。
4. 直接比较早期原始 mock-aligned-v2.json 被评分版本门禁拒绝；改为第一批已离线重判的 mock-scored-final.json 后通过，未关闭版本检查。
5. 全项目 mypy：68源码、9文件16既有错误；verifier 文件本批有引用保护改动，但它的两处数值类型错误未变。本批新增代码没有新增类型诊断；全项目类型门禁仍未通过。

主要实际命令（根目录，除特别注明）：

```powershell
$env:RESOLVEFLOW_AGENT_DB='postgresql://agent:agent@127.0.0.1:55433/agent_db'
agent/.venv/Scripts/python.exe scripts/agent_eval.py mock --output reports/agent-context-batch2/mock-complete.json
agent/.venv/Scripts/python.exe reports/agent-context-batch2/measure.py
agent/.venv/Scripts/python.exe scripts/agent_eval.py compare --baseline reports/agent-alignment-batch1/mock-scored-final.json --input-report reports/agent-context-batch2/mock-complete.json --output reports/agent-context-batch2/compare.json
./eval.ps1 -Mode harness -Output reports/agent-context-batch2/harness-final.json
./eval.ps1 -Mode replay -Output reports/agent-context-batch2/replay-final.json
./eval.ps1 -Output reports/agent-context-batch2/validate-v2.json
./eval.ps1 -Dataset evals/current -Output reports/agent-context-batch2/validate-v1.json
# 在 agent 目录运行：./.venv/Scripts/python.exe -m mypy
```

320项集中 pytest 文件清单在 tests-final.xml；覆盖 test_context_*、test_harness_loop、test_observation_read、test_sdk_adapter、test_proposal_verifier、四个评测单元文件、SDK/材料恢复、recovery_*、strict/export/golden回放、真实MCP及评测接线。新增两个模块为 test_context_batch2.py 与 test_material_archive_recovery.py，共10个新测试。最终五包由 test_replay_golden.py -k golden_trajectory 配合 RESOLVEFLOW_REPLAY_GOLDEN_DIR 导出。

未运行真实 LLM 语义质量、人审、Java整链或网页部署；检索算法和重排未变。巨大材料元数据、问答或必保留政策仍可能真正超限，此时拒绝而非删条件。后续调查策略/RAG/有限Live由用户另行决定，本批停止于提交与正常推送。
