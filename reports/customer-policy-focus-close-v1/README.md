# 政策追问质量收口（2026-10-23）

按用户“完成收口政策追问这个质量缺口”实施。原失败记录在[单场景真实确认](../customer-policy-focus-live-v1/README.md)，不覆盖原输出或Gold。

## 第一步：有界完整政策上下文

现有每店仅六条短政策，原Query前三漏掉两条关键规则。客服`search_policy`现先检查原绑定政策集合是否足够小：不超过8条且包含来源字段的序列化UTF-8内容不超过8192字节时返回全部原文；超限仍走原三路/可选双分支检索。共同复用原商家、manifest、READY generation及行数完整性校验，不使用规则ID或问题关键词挑政策，不改旧索引。

`top_k`是排序路径的结果数，小集合完整返回允许多于它；工具说明/schema显式写明，观察标注`retrieval_context.mode=COMPLETE_SMALL_SET/count`，运行manifest记录版本/上限。这个模式不做dense/BM25或embedding降级冒充，完整上下文的path明确为complete；检索模式保持原错误语义。

[offline.json](offline.json)使用原真实Query及原generation，只读实际PG、不加载embedding，六条均完整返回，单次20.96ms，public全表hash保持、新LLM/HTTP0。这保证这个小集合的条款覆盖，不证明选取相关条款/回答质量，也不当作大语料RAG效果或性能百分位。

实际验证：

- `RESOLVEFLOW_AGENT_DB=postgresql://agent:agent@127.0.0.1:55433/agent_db`；在agent目录执行pytest，关键新增测试先红：初次测试参数ID过长造成2个setup错误，缩短ID后另有测试语料超4000字，改为合法长规则；缺能力的红测保留。实现首轮canonical不接受float score，改用无排序整数零后通过。
- `pytest tests/unit/test_support_sources.py tests/unit/test_support_retrieval.py tests/integration/test_policy_index.py tests/integration/test_support_retrieval_index.py tests/integration/test_support_small_policy.py tests/integration/test_support_staged_api.py tests/integration/test_support_stream_runtime.py tests/integration/test_policy_focus_live_driver.py -q --tb=short`：**53通过、0跳过（28.44秒）**，包含真实PG/SDK、原排序路径、完整供给、大小限制、绑定generation与跨商家拒绝、流式及隔离driver。原第三方Starlette弃用警告1项。
- 三个主要改动源码strict mypy通过；新增service manifest及最终格式另做Ruff。原四脏文件/旧清单/probe与原真实结果SHA保持；未新增真实模型请求，账仍2025。

下一步同一授权内处理上下文中的历史/当前事实区分，再冻结有限真实确认，判断模型是否能从完整集合选择相关条款。当前不能凭完整供给就称最终回答已修复。

## 第二步：历史来源与条件解释范围

历史助手、客户和商家原文分别标记`HISTORICAL_ASSISTANT_OUTPUT / CUSTOMER_STATEMENT / MERCHANT_STATEMENT`，覆盖最近消息、历史预览及精确回读，不改持久原文，不把历史消息放入fact_view。已接受焦点若需要POLICY且不需要ORDER/SHIPMENT，stage显式给出`policy_scope=CONDITIONS`；模型应按相关主题解释条件，不能借旧助手发言认定本单当前状态。需要判断本单时仍可自主追加事实需要并读取，不固定所有政策问题先查物流。

- 两个新增关键断言先红（2失败/20通过），实现后定向42通过。首次扩大`-k support`选中353通过、4跳过、1失败；失败为较长目录说明令旧Mock保守包溢出，去掉目录重复说明、保留schema/观察中的完整模式说明后，**精确客服单元+实际SDK/PG/流式/完整供给/旧确认driver共328通过、0跳过（23.47秒）**。不增加预算或删除原断言。首strict发现authority的Optional键类型，明确转换后strict三源码通过；Ruff通过。
- 新三场景驱动`scripts/close_policy_focus_live_v1.py`复用既有真实流式/发送前记账/独立schema驱动，整组硬上限12次模型、3个独立追问、每题一次、失败不重跑，有限结构修复仍计费计数。两项驱动单元通过（2.25秒），验证旧历史/事实/pin不改、整组上限在发送前生效、失败清理driver配置、不可再次执行；Ruff/py_compile通过。
- `prepare`已冻结[三场景计划](../../evals/customer-policy-focus-close-v1/plan.json)、[逐场景输入/源码SHA](live/manifest.json)：原追问、切换质量问题、假设未来承运商确认丢失。沿用原合成历史/业务快照和真实本地政策，新run、原public保持；不测浏览器或简历，不强制工具路径/分支，新增真实模型仍0、usage2025。准备提交普通push核实后，仅执行本组一次并审查全部输出。
