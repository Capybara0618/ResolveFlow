# 商城事实与Agent场景门禁验证

日期2026-10-04。真实服务读取、合成单元输入、脚本模型分别说明；新增收费模型请求0。方案见[规格](../docs/agent-commerce-facts.md)，当前进度仅在tasks/todo.md顶部。

## 本批结果

- 单SQL读取实际支付账本/明确履约主记录，Java生产消费及core契约/fixture同步；不造历史未发货、不新增工具或迁移。
- 工具引用版本覆盖订单/付款/履约版本，hash覆盖完整原文；P2真实order_status/资金/履约事实保真，同源旧读失效但原文保留。
- 未发货退款按付款/明确履约/整行余额与槽检查，不强制读无关承运物流；新物流冲突或退款占用不能隐瞒。未发货条款不适用不允许直接拒绝整个申请。其他拒绝仍保守要求订单/物流和政策。
- SDK＋PG索引脚本模型两例通过：订单→检索→退款3调用；已发货错误退款被拦截后一次修复转人工4调用。调用是MockModelClient，不是DeepSeek，也不代表召回率/建议准确率。
- 新context/verifier manifest，不修改旧run/Observation/预算，不自动重算已有建议；Java当前复核和商家最终审批保留。

## 实际验证

Java统一先设 `$env:JAVA_HOME='C:/Users/hjn/.jdks/jdk-21.0.12.1+1'`：

```powershell
.\java\mvnw.cmd -f java/pom.xml -B -pl commerce-service,case-service -am '-Dtest=AgentOrderFactsDatabaseTest,OrderLineContextControllerTest,CommerceOrderLineClientTest,ManualProposalApiTest,UnshippedRefundCheckTest,FulfillmentDatabaseTest,ProposalReCheckApiTest,ReviewDecisionApiTest' '-Dsurefire.failIfNoSpecifiedTests=false' test
.\java\mvnw.cmd -f java/pom.xml -B -pl commerce-service -am '-Dtest=OrderLineReadServiceDatabaseTest' '-Dsurefire.failIfNoSpecifiedTests=false' test
.\java\mvnw.cmd -f java/pom.xml -B -pl commerce-service,case-service '-DspotlessFiles=.*LineContextRow.java,.*OrderLineRepository.java,.*OrderLineController.java,.*CommerceOrderLineClient.java,.*OrderLineContextControllerTest.java,.*AgentOrderFactsDatabaseTest.java,.*CommerceOrderLineClientTest.java' spotless:check
```

第一命令Commerce13＋Case84，0失败/0跳过；第二独立分页/隔离12通过；定点格式通过。测试使用独立Testcontainers MySQL，未修改体验数据库。

Python设置 `$env:RESOLVEFLOW_AGENT_DB='postgresql://agent:agent@127.0.0.1:55433/agent_db'`，实际25文件回归：

```powershell
agent/.venv/Scripts/python.exe -m pytest agent/tests/unit/test_agent_order_facts.py agent/tests/integration/test_unshipped_agent_flow.py agent/tests/unit/test_context_quality.py agent/tests/unit/test_context_builder.py agent/tests/unit/test_context_citation_survival.py agent/tests/unit/test_context_facts.py agent/tests/unit/test_context_scenarios.py agent/tests/unit/test_proposal_verifier.py agent/tests/unit/test_loop_semantics.py agent/tests/unit/test_sdk_adapter.py agent/tests/unit/test_harness_manifest.py agent/tests/unit/test_action_repair_notice.py agent/tests/unit/test_build_identity.py agent/tests/unit/test_tool_catalog.py agent/tests/unit/test_contracts_multiline_money.py agent/tests/unit/test_contracts_core_corpus.py agent/tests/unit/test_contracts_core_reject.py agent/tests/integration/test_context_wiring.py agent/tests/integration/test_sdk_durable_recovery.py agent/tests/integration/test_policy_search_action.py agent/tests/integration/test_reviewer_diagnostics.py agent/tests/integration/test_recovery_request.py agent/tests/integration/test_recovery_budget_store.py agent/tests/integration/test_strict_replay.py agent/tests/integration/test_replay_golden.py -q --tb=line
agent/.venv/Scripts/python.exe -m pytest agent/tests/unit/test_agent_order_facts.py agent/tests/integration/test_mcp_tools.py agent/tests/integration/test_tool_credential.py -q --tb=line
agent/.venv/Scripts/python.exe scripts/agent_context_audit.py --output tmp/agent-facts-context-after.json
```

25文件314通过，5旧committed_golden_pack仍PACK_INVALID（manual_review/question/escalation/read_then_review/read_then_question），0跳过；上一批已隔离复测该既有失败。没有删断言、升级旧包或放松manifest；本版本生成的strict/恢复测试通过。第二命令42通过，包含真实MCP stdio和凭据边界，模型请求0。最终定向`python -m pytest agent/tests/unit/test_agent_order_facts.py -q --tb=line`22通过。

八个上一批合成ContextPacket总ESTIMATED35305（上一批34217，增加必要提示；原改前39816），UTF8字节估算不是实际计费token。没有宣称本批省token。真实新履约字段可受预算裁剪保护，完整SDK测试未提高预算。Ruff本批7生产文件/2新测试及git diff --check通过。

## 过程中失败与修复

- Maven首次未引号属性被PowerShell拆分；改为单引号。主机默认JDK17被enforcer拒绝，显式使用已有JDK21，未改锁。
- Java先写关键测试，新增字段不存在导致编译失败；实现后MyBatis多构造器缺明确选择导致1error/2fail，增加AutomapConstructor后通过。
- Python关键测试改前15fail/3pass，改后通过；新SDK测试误把Literal当Enum，改用真实`path='dense'`后2通过。
- 定点格式参数先误用glob及正则竖线，失败后使用逗号分隔安全正则，最终定点check通过，未格式化历史脏文件。
- 将购物测试与旧固定行数分页测试合跑时，已有Fulfillment测试创建订单导致分页2fail；保留原断言，分页独立新容器12通过。尝试外层测试事务回滚导致付款REQUIRES_NEW锁等待，撤去外层事务，真实交易测试单独在测试容器运行通过。未改生产事务语义。

## 运行与未运行

代码2149f50已普通push到origin/main并核实远端SHA。实际`.\stop.ps1`和`.\start.ps1 -NoBrowser`均返回0，重建当前三个Java JAR并加载新Agent，九项健康；政策import0/同hash跳过3，索引READY，网页5174。未用SkipBuild复用旧JAR。

忽略tmp/agent_facts_snapshot.py经受控demo容器只读逐表摘要，部署前后50业务表行数/hash全部一致；Agent仍4COMPLETED/15模型/10工具/8回调，无新模型/退款/交易。tmp/agent_facts_runtime_read.py以真实内部HTTP调用工具核对现有4行：新增三字段与数据库版本/主体一致，core schema与P2事实全部通过，商城公共GET200。两驱动不提交原数据/凭据；提交的[机器报告](agent-commerce-facts-runtime.json)只有脱敏结果。旧服务的初始status九项健康也返回0。

没有真实DeepSeek效果评测、当前商城RAG召回标注基线、网页视觉重验、全仓Java/前端回归。页面未改，RAG排序未改，旧建议不重新调查。下一步按当前政策和场景建立离线召回基线，再决定检索优化与有限Live验证。
