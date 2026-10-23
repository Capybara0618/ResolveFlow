# 单场景真实政策追问确认（2026-10-23）

用户明确批准执行[原计划](../../evals/customer-policy-focus-v1/live-plan.json)：原追问只跑一次、至多12次模型请求，不强制子Query、不自动重跑，不作为简历指标。生产基线9b7700c。

## 固定输入与运行边界

[input.json](input.json)来自原第二轮真实验收的合成会话历史/旧事项，当前追问原文不变。订单、物流只读响应取原保存快照，明确不是本轮实时Java查询；本店政策使用原run绑定的真实本地PG generation和现有embedding。新run及调用账仅在自建临时schema，public全表前后校验，导出后仅删除本次schema。Java/Web不启动，不写当前客户会话/退款，不调整政策、Gold或原运行结果。

`SupportRuntime`→原AgentScope staged-v1→实际`StreamingLiveModelClient`子类执行，Provider为DeepSeek Flash、thinking禁用、JSON、temperature0，输出仍由原1024/step和12次/活动deadline约束。计数在发送前保存，实际请求/回应/Query/引用及失败全记录；流式客户端无内部重试。预热单列，Agent运行时间包含SDK/模型/检索/PG，不是网页首字或p95。

## 预跑

- 两个单元测试验证发送前记账、硬上限不多发、逐块正文观察、快照run绑定与未知读取404；真实PG/实际生产运行入口+合成Provider SSE端到端，3次合成模型请求全部在测试私有账/临时schema，验证导出/清理及public不变。
- `PYTHONPATH=E:/Code/Agent+Backend`、`RESOLVEFLOW_AGENT_DB=postgresql://agent:agent@127.0.0.1:55433/agent_db`：单元+集成 **3通过、0跳过（14.72秒）**。Ruff首轮发现缺BoundSources导入/冗余noqa及测试导入/长行，修正后Ruff和py_compile通过；尚未发送真实请求。
- `scripts/confirm_policy_focus_live_v1.py prepare`：原policy generation就绪匹配，冻结[源码及输入SHA](manifest.json)，新增模型0。原账仍2022。

## 待执行

先提交准备，再同脚本`execute`一次；结果由Codex按原来源审核Query是否保留语境、两种政策边界是否取得、回答是否聚焦且不编造必交材料。模型可选单Query或分支；不以必须触发新能力作为正确标准。原始结果不得覆盖；有失败也保留。
