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
