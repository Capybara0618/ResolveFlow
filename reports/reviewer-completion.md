# 审查侧收尾记录

2026-09-30，按用户最新要求继续完善审查侧，并授权使用用户环境变量中的DeepSeek V4.1 Flash密钥进行有限真实验证。用户侧界面改造待审查侧完成后开展。

## 修订输入闭环

原缺口：材料和问答已在Case持久化，但下一轮Agent只有描述和材料ID，无法知道已经回答的问题和人工核验结论。

新增可选`RunRequest.request.review_context`：包含当前修订之前的客户材料、人工核验记录，以及最多两轮原始问题。材料携带原文、证据ID、来源/版本/hash、question_id、被核验材料ID与结构化结论；Case按工单和修订投影。引用身份仍为原来的四项，快照不代替工具Observation或资金授权。

Agent在接收时拒绝未来修订或未列于evidence_refs的材料，将快照纳入请求哈希并写入新增PG列。旧请求没有快照时哈希保持原样。普通领取、fenced恢复和合成strict导出都传递同一快照；模型实际请求的P1层保留问答与人工结论，溢出时显式转人工而不丢掉关键事实。旧运行和历史回放包没有被修改。

验证命令：

```powershell
$env:RESOLVEFLOW_AGENT_DB='postgresql://agent:agent@127.0.0.1:55433/agent_db'
agent/.venv/Scripts/python.exe -m pytest agent/tests/integration/test_reviewer_input.py agent/tests/integration/test_reviewer_diagnostics.py agent/tests/integration/test_run_store.py agent/tests/integration/test_run_api.py agent/tests/integration/test_run_lease.py agent/tests/integration/test_sdk_durable_recovery.py agent/tests/unit/test_context_builder.py -q
./java/mvnw.cmd -f java/pom.xml -B -ntp -pl case-service -am '-Dtest=ReviewerRunInputTest,AgentRunDispatchApiTest' '-Dsurefire.failIfNoSpecifiedTests=false' test
```

结果：Python92 passed，Java9 passed。契约/OpenAPI/上下文初次检查185 passed、37因DB停机skipped；数据库启动后相关37项已包含在92项实测内并通过。后端三个JAR从当前源码构建通过，隔离演示环境恢复成功。未把skip记作通过。新增测试覆盖修订过滤、问题与回答关联、人工核验原文、保存与恢复、改答案同键409，以及实际SDK模型请求保留这些信息。

真实模型验证、浏览器动作验收及启动入口接入将在后续段落记录实际结果。
