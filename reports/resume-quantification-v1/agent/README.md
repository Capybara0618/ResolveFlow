# Agent动态调查与固定流程：正式128次

2026-10-07。32个冻结合成业务场景，每组每场景2次；相同deepseek-flash、temperature=0、JSON/1024输出、12次单run预算、相同BM25→rerank业务检索C及生产上下文/引用校验。唯一生产循环仍由AgentScope 2.0.8驱动，固定流程仅供评测。真实LLM、隔离PG及生产MCP接线到冻结合成只读源；不是Java业务端到端成绩。

| 指标 | 固定流程 | 动态Agent |
| --- | --- | --- |
| 整体有效建议 | 62/64（96.88%） | 56/64（87.50%） |
| 复杂子集有效建议 | 50/52（96.15%） | 44/52（84.62%） |
| 自动Gold联合 | 62/64 | 52/64 |
| 完成终局 | 64/64 | 56/64 |
| 实际模型请求/平均每次调查 | 137 / 2.14 | 300 / 4.69 |
| 实际HTTP读取 | 192 | 159 |
| 工具尝试（含本地检索） | 256 | 218 |
| 实际input/output token | 312846 / 23753 | 535099 / 34962 |
| 平均/p50/p95调查耗时 | 8.924 / 8.755 / 10.921秒 | 10.747 / 11.438 / 13.958秒 |

437次真实模型请求均取得provider usage，未知/估算0。失败保留在64次分母；复杂分类在运行前冻结，26个场景各2次。三类家族（未发货、物流丢失、签收争议）两组均16/16有效；质量问题固定14/16、动态8/16。总体动态比固定低9.375个百分点，复杂子集低11.538个百分点。动态HTTP读取少17.19%，但模型请求多118.98%，token与时延也更高，不能称整体效率提升。

## 来源复核

[128条逐例表](cases.md)、[Codex判断](../../../evals/resume-quantification-v1/agent-review.json)及[汇总](summary.json)绑定原始文件hash。NONBLIND工程复核，不是独立人工盲测。主动作与来源/政策矛盾记FAIL；表达细节/条件/责任可改进但主建议仍可执行记WARN且计有效；未完成一律无效。REQUEST_INFO只建议商家补证，不代表发出了客户问题。

- 动态A12B两轮：材料503后立即明确系统读取失败、未知签收人、商家调取承运记录的下一步，合理ESCALATE。自动Gold因少读预设工具判错，语义复核接纳，不强迫固定路径。
- 动态A15B第0轮：已知REFUTED后建议新客观证据/复核，保留其他理由与无其他有效理由才考虑拒绝的条件，主动作REQUEST_INFO有效；职责精度WARN。
- 动态A16B第1轮：故障材料补证合理，主动作有效；已有RESERVED核查遗漏、系统订单信息不应由客户提供记WARN。
- 固定A15B两轮：虽然文字限定质量理由，但整体动作REJECT且下一步明确驳回本次申请；源材料仍有其他理由待调查，记无效。
- 动态8次未完成：INVESTIGATION_FACTS_REQUIRED 1、FINDING_SOURCE_INVALID 6、ACTION_REFUSED 1。终止保护生效，不是已经形成合理人工建议。
- A14B原合成数据electronics与家居材料条款的品类矛盾保留，通用照片补证和R-DMG-001支持当前补证；不声称已满足退款条件。签收底单/商家核验责任、重复询问及省略占用条件均逐例保留WARN。

固定流程在当前小而稳定的业务包上更可靠；动态组能提前结束失败调查、按事实省略部分HTTP读取，但质量场景引用和事实门禁导致停止。简历展示动态调查实现、32场景128次对照及87.5%有效建议；删除“相较固定流程准确率/复杂处理提升”的预设表达。下一步优化依据这些未完成轨迹，本轮不补跑刷分。

## 复算与资产

`agent/.venv/Scripts/python.exe scripts/resume_agent_summary.py` 无网络、无模型请求，重新核对128个键及决策/来源hash，输出summary和cases。Ruff通过；两次复算语义及数值一致。所有模型请求、prompt/P2条款、usage、Observations、轨迹、HTTP读与失败在[formal-v1](formal-v1.json)；开发试跑与原数据修正说明见[试跑1](trial-v1.json)、[试跑2](trial-v2.json)和[输入分叉说明](../../../evals/resume-quantification-v1/business-v1/README.md)。实际检索query与返回排名在轨迹，不新增query Gold，不将运行内检索调用次数解释为100%召回。

正式运行命令为 `scripts/resume_agent_comparison.py --dataset evals/resume-quantification-v1/business-v1 --variant C --reranker <本地BGE-reranker-base snapshot> --output reports/resume-quantification-v1/agent/formal-v1.json`（模型密钥通过既有环境变量；已存在输出不应覆盖）。正式时Python生产源码与锁均冻结，报告code_hashes/runner_sha256/manifest为依据；后续Java资金修复未改变本批Python版本。原Gold及旧报告保留。
