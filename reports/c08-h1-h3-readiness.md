# C08/H1–H3 接续核查（2026-09-26）

当前 mock 全服务退款闭环已通过，不能当作 H1 的模型自主性证据。`docs/agent-harness.md` 要求 H1 至少6组“同诉求、不同证据”的配对案例，并记录模型动作与真实调用对应，允许多个正确路径。`docs/evaluation.md` 要求这些家族归入后续80个合成案例、整个家族只落dev或冻结test；正式live小样本不能用mock替代。

以下是准备给真实模型的**合成案例设计**，不是已执行或已人工审定的Gold。每对两侧保持诉求、主体、政策版本与工具权限一致，只改变列出的权威证据；合法动作集合还需在运行前冻结，不能看过模型回答后改Gold。

| 对 | 相同诉求 | A证据变化与允许结论 | B证据变化与禁止事项 |
| --- | --- | --- | --- |
| H1-01 | “包裹丢失，请退款” | 物流结论LOST；有适用政策，可提出带引用REFUND | 物流DELIVERED；不得仅凭诉求建议REFUND |
| H1-02 | “包裹未到，请退款” | 承运商明确LOST；可提出REFUND | 仍IN_TRANSIT且未过调查窗口；应补证/人工，不得把未到当已丢失 |
| H1-03 | “物品破损，请退款” | Case有可核验的破损材料与适用政策；可建议REFUND或人工确认 | 仅有无来源的描述；应追问材料，不得把模型猜测作证据 |
| H1-04 | “物流丢失，请退款” | 行类目受当前固定政策覆盖；可建议REFUND | 相同物流事实但行类目不在规则范围；不得引用不适用规则退款 |
| H1-05 | “包裹丢失，请退款” | 同行退款槽FREE且账本尚未退款；可建议REFUND | 同行已成功退款；不得建议第二次付款 |
| H1-06 | “包裹丢失，请退款” | Java工具/政策证据完整；可按引用作结论 | 关键工具持续不可用或返回无版本内容；应追问/转人工，不得伪造引用 |

每次运行需保存实际模型请求hash、manifest/模型版本、动作及工具调用序列、Observation来源与hash、候选方案及Java复核结果、预算/超时/失败；模型可选择多种安全路径，不预设全五工具链。先用同一模型与参数跑12个配对case，每run保持现有上限12次模型、16次外部工具/检索、累计输入40000/输出4000；12 run的**规格理论上限**为144次模型调用、48万输入/4.8万输出token，实际成本依provider报价与调用结果计算，不能把上限写成已消费。收费运行前须确认具体endpoint/model、全局费用上限和可用余额；当前环境 `RESOLVEFLOW_MODEL_ENDPOINT`、`RESOLVEFLOW_MODEL_ID`、`RESOLVEFLOW_MODEL_API_KEY` 均未配置，本轮未联网调用模型。

H2/H3离线核查：工作目录 `agent/` 执行
`./.venv/Scripts/python.exe -m pytest tests/unit/test_context_builder.py tests/unit/test_context_facts.py tests/unit/test_context_scenarios.py tests/unit/test_context_trimming_demo.py tests/unit/test_harness_loop.py tests/unit/test_loop_semantics.py tests/integration/test_context_wiring.py tests/integration/test_run_worker.py -q -p no:cacheprovider --tb=short` → **160 passed**。覆盖同输入上下文hash、金额/来源/冲突保护、scope读回、预算上限、无进展反馈/不同页、取消竞争；这只是测试覆盖，不等于所有生产恢复时的持久预算已完成（归C09）。前一小步全量Python **1055 passed/9 skipped**；本次没有重跑全量、Java、all-offline或live，也未做H1评分，H1–H3保持未勾。

下一具体动作：先将6组案例落成可执行的隔离合成fixture与冻结Gold/运行记录结构，离线验证不会向模型泄露Gold，也不会改变真实业务权限；准备好后取得用户明确的模型与费用上限再调用live。若无预算，继续C08离线门禁与后续独立工作，但不得宣称H1通过。
