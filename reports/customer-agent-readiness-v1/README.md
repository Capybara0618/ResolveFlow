# 客服 Agent 评测前工程验收

2026-10-21。按用户“做到可以开始评测前，暂不更新简历”授权完成 [实施设计](../../docs/customer-agent-readiness-v1.md)。本批没有执行正式模型效果评测，不产生新准确率/完成率/提速指标。

## 已实现

- 同次模型决策中的意图/多诉求任务标注：最多8项，区分物流、资格、办理、核查、商品及其他。任务状态/依据/回答原句可审计；live首次须给任务，更新不能静默删项，回答不能遗留PENDING。共享一次既有纠错机会，无额外分类/摘要模型，不固定工具路径。旧mock脚本兼容不代表其理解了任务。
- 实际请求预算驱动的上下文：当前问题、绑定状态、政策/业务原文保护；先保留最近原文，再降为首尾预览/带位置索引，最后为省略索引的H引用。重复依据去重，不同版本/冲突保留，政策条件与例外不按句子机械裁剪。装不下的必需上下文明示CONTEXT_REQUIRED_OVERFLOW，不扩大窗口。
- `read_context`按本轮已知H序号、Unicode字符偏移精确读回，受原local预算/调用账约束。未知引用不会访问任意会话。远程history大原文留原件、以索引投影，可再读取尾部；整体仍受256KiB限制。当前请求与原始历史没有被改写为模型摘要。
- Java按已锁定会话/输入/fence冻结前轮模型任务提示，Python校验并移除旧引用和旧回答片段，当前轮重新判断。任务不是系统事实/业务授权，不进入客户消息元数据，无新增公共字段或数据库迁移。
- 运行manifest包括新任务/上下文模块及实际token计数器；持久结果恢复重新构造相同状态/请求，不新增模型/外部业务读。
- RAG沿用本店/适用版本/generation硬绑定、单Query三路RRF、完整政策与独立指南。Query由Agent根据新上下文/未完成诉求在同次决策生成，原调用账记录Query及结果。未加入额外改写模型/CE，未改变原知识或重建生产索引。

已分别验证并普通推送：设计41fc2f1、任务529fbca、上下文9083814、跨轮1aaa335。最终准备及证据单独提交，SHA在交付回复/后续账本记录中说明，不递归改自身提交。

## 工程验证

最终指定Python19文件 **96通过、0失败/跳过**。含工具/任务/上下文/来源/契约、原诊断驱动、真实隔离PG、三轮实际ASGI→SupportRuntime→AgentScope→PG。三轮模型是明确脚本，使用本地固定tokenizer核对请求预算；6个脚本决策不是真实API调用或质量成绩。前轮实际脚本回答进入下一轮，尾部纠正由远程history再本地片段读回，找到包裹后撤回诉求，第三轮重新引用指南，重复派发不增加调用。

Java JDK21、隔离Testcontainers MySQL与真实HTTP：SupportApiTest **15**、SupportWireTest **2**，共 **17通过、0失败/错误/跳过**。覆盖同会话任务冻结、不同商品隔离、内部状态不出客户投影，以及原版本/fence/共享/人工接续。未同时启动Java+Python+浏览器进行新全栈体验。

6修改生产Python模块strict mypy通过；agent目录相关Ruff、仓库根准备脚本/新测试Ruff通过；两自有Java文件Spotless apply、git diff --check通过。旧Starlette与Mockito警告保留；原退款3个已知失败未重跑，不称全仓绿。前端/退款权限/资金模块没修改，不重复做不相关压测或网页构建。

最终复现命令在agent目录（PG55433可用，`RESOLVEFLOW_AGENT_DB=postgresql://agent:agent@127.0.0.1:55433/agent_db`，`PYTHONPATH`为仓库根）：

```powershell
.venv/Scripts/python.exe -m pytest tests/unit/test_customer_agent_readiness.py tests/unit/test_customer_agent_live_v3.py tests/unit/test_customer_rag_live_v2.py tests/integration/test_customer_rag_live_v2.py tests/unit/test_support_agent.py tests/unit/test_support_guidance.py tests/unit/test_support_recovery.py tests/unit/test_support_guide.py tests/unit/test_support_sources.py tests/unit/test_support_retrieval.py tests/unit/test_support_api.py tests/unit/test_contracts_support.py tests/unit/test_contracts_support_agent.py tests/unit/test_support_tasks.py tests/unit/test_support_context.py tests/integration/test_support_store.py tests/integration/test_support_retrieval_index.py tests/integration/test_support_guide_api.py tests/integration/test_support_readiness_api.py -q
```

Java在java目录：`mvnw.cmd -pl case-service -am -Dtest=SupportApiTest,SupportWireTest -Dsurefire.failIfNoSpecifiedTests=false test -q`。

## 开发中的失败

- 任务红测3失败/1通过，接线后guide因重复提示超出旧预算，精简说明后通过；未扩大上下文。
- 上下文红测4失败/1通过；追加目录/跨轮提示也曾使保守字节估计的guide测试超限，再精简重复说明，最终保留完整指南、旧预算和原断言。
- 初次PG误用环境变量导致8跳过，改用实际fixture读取的RESOLVEFLOW_AGENT_DB后8真实通过；最终96全无跳过。
- Java跨轮先红1失败；首版误查turn表不存在的主体列，导致15中5失败/1错误，改为已锁定会话的作用域查询后14通过/新测试1失败；新测试把首条消息版本误写1（实际为2），改按实际输入版本断言后17全部通过。没有删除旧断言。
- 准备脚本缺失时新测试收集错误1；完成脚本、冻结输入和预检后4单元+1三轮集成通过。新代码行长告警修正；从根检查agent测试曾产生导入分类告警，使用agent配置工作目录，不为此重排旧测试。

- 最终暂存检查发现新JSON为CRLF，被仓库识别为行尾空白；归档本批提交前原字节，转LF并核对JSON语义完全相同，更新准备清单的打包hash，再跑预检/准备测试。不改旧Gold、旧结果或生产逻辑。

原始工程日志保留在忽略的`tmp/customer-agent-readiness-v1/`及`tmp/customer-agent-readiness-java-*.log`；无凭据/真实用户数据的汇总见[收口记录](completion.json)。

## 评测材料与停止位置

[冻结准备](../../evals/customer-agent-readiness-v1/README.md)包含12类/36轮输入、逐轮语义条件、实际前轮结果构造及只读预检；开发/验收变体均合成且开发者可见，不称独立人审或盲测。绑定29份源码/输入/既有知识文件，预检成功；真实PG两店generation/归属可用，11公共表before/after及上批v3见证一致。

此时可以开始模型效果评测；正式双组调度与语义复核按冻结协议在后续评测阶段执行，当前预检入口不执行这些动作。Agent主指标为全部必要诉求/轮次完成率，RAG主指标为必要依据完整覆盖，token/模型请求/检索及完整接口时间辅助。固定流程不预设必败，不能因结构标记ANSWERED就自动给业务正确。

P03一类决定性条件遗漏、口语Query漏召回、新多轮质量和客户措辞仍须真实模型验证；本批没有新的效果结果，也不以工程测试宣布它们已经解决。恢复测试不是任意跨版本strict回放支持，旧run/manifest不静默升级。

模型API新增0，累计调用账仍1540。原四历史脏文件hash保持，旧报告/Gold/简历保持；无新权重/依赖/政策发布/原业务队列消费。测试schema清理，PG停止、卷保留，10个项目端口关闭。保持停在正式评测前。
