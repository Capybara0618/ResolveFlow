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

## DeepSeek 与 Agent/RAG 收尾

已接入官方 `deepseek-flash`，本轮查询官方模型列表确认可用。使用 JSON 输出、关闭 thinking、temperature=0；密钥只通过环境变量传给 Agent 进程，不写入仓库、启动参数或报告。日常启动方式如下，必须先启动 Docker Desktop，并已按 README 安装项目依赖：

```powershell
.\demo.ps1 -Live
.\demo.ps1 status
.\demo.ps1 stop
```

浏览器地址 `http://127.0.0.1:5174`，审核账号 `demo-reviewer / demo-pass-1003`。`-Live` 启动常驻真实调查：新工单或材料修订经调度自动调用模型；浏览已有完成记录不会重新调用。无 `-Live` 时只启动只读 Agent API，不开展新调查。两种模式都保留 Java/MQ 的模拟退款执行；stop 保留数据卷。已有构建可加 `-SkipBuild`，不自动打开浏览器可加 `-NoBrowser`。

真实请求暴露并修复了几项离线 mock 无法证明的问题：

- 动作说明明确扁平 JSON、必填 kind、合法枚举、引用数组结构；格式修复只反馈有限字段错误，保留一次修复上限，不回显整份模型输入。
- P2 保护工具来源身份，以及已召回政策的完整条件和例外。P3 摘要裁剪不能丢掉这些内容；读取 Observation 的局部窗口仍引用原来源，不拿窗口 hash 冒充原文。
- 上下文计数包含实际消息 JSON 转义与封装，避免“文本能放下、持久化请求预算却拒绝”的差异。DeepSeek 部署容量设置为 32768，但每步输入硬上限仍为 8192、每次输出最多 1024、默认每 run 最多 12 次模型调用；没有扩大领域权限。
- 中文提示要求区分客户陈述、人工结论、模型推断；INCONCLUSIVE 表示无法判定，不自动形成冲突。冲突要求至少两个来源；不得把嵌套材料 ID 当成工具 Observation 身份。政策适用性结论必须有实际检索依据。
- manifest 记录新上下文/计数版本和模型参数，旧运行不得静默换版本恢复。有限验收脚本复用生产 RunWorker/AgentScope/MCP/RAG，不增加第二条生产循环。

前端同步修复 SSE 推进工单版本后审核上下文不刷新的问题，并阻止迟到请求覆盖当前修订。时间线增加中文调查失败、补证与人工处理文案；顶部不再把所有模型结果标为 mock。浏览器拒绝操作还发现“已结束工单被提示新调查已排队”，现已改成终态只读提示，并只在真实 QUEUED 状态显示排队。

## 实际闭环结果

以下都是隔离演示库的新合成工单；没有修改真实用户订单。脱敏结构化结果见 [live-acceptance.json](reviewer-completion/live-acceptance.json)，失败运行保留。

| 场景 | 工单 ID | 实际结果 |
| --- | --- | --- |
| 丢失、批准 | eb16fd70-82e3-42d4-92bf-95b2ff2f57e3 | 真实模型建议，浏览器人工批准 32900 分，经 MQ/provider 模拟执行，CLOSED_SUCCESS、授权 CONSUMED |
| 丢失、留待体验 | bcaa700e-8088-4917-81d3-be812dc049ce | 常驻 Agent 自动读订单/物流、检索政策，Java VALIDATED；32900 分待人工审批，未代替用户批准 |
| 补证后调查、拒绝 | 389b4ae2-efaf-4071-bff0-0f78f2733415 | 浏览器要求补证，客户通过认证 API 回答原 question_id，人工核验及补充材料触发新修订；最终模型保留已答内容、不重复追问并转人工。浏览器人工拒绝后第 7 版 CLOSED_REJECTED，旧建议失效、页面只读 |
| 签收争议 | aa108d9b-e0c7-497c-a0fd-ba8dbf5b6a33 | 最终建议人工复核、没有退款授权。模型承认仍需独立签收凭证；最终运行没有查询承运商，不能把它描述为已核对双方原始来源 |
| 损坏但无法核验 | d97285fb-dc2e-4514-bfde-17c422d191b4 | 最新运行区分损坏主张与人工 INCONCLUSIVE，引用实际工具来源，建议人工复核；没有宣称图片已验证，也没有退款授权 |

客户补证使用 API 是本轮审查侧验收手段，不能据此宣称用户侧网页已经完成。本轮浏览器实测了批准、要求补证和拒绝；模拟退款结果、旧版失效、关闭后只读均已核对。先前 mock UNKNOWN 保持原 operation 的证据沿用 [演示报告](reviewer-demo/README.md)，本轮没有重复制造付款未知状态。

![真实模型待审工单](reviewer-completion/live-workbench.jpg)

另见 [批准后结果](reviewer-completion/approve.jpg)、[拒绝后只读状态](reviewer-completion/rejected.jpg)。

## 集中验证与调用记录

2026-09-30 最终相关 Python 集合 **235 passed**；前端 **73 passed（12 个测试文件）**，`vue-tsc` 和 Vite 构建通过。前述 Java **9 passed** 与三个当前 JAR 构建在本轮输入协议修改后完成，后续未再修改 Java，未重复运行。

```powershell
$env:RESOLVEFLOW_AGENT_DB='postgresql://agent:agent@127.0.0.1:55433/agent_db'
agent/.venv/Scripts/python.exe -m pytest agent/tests/unit/test_context_builder.py agent/tests/unit/test_context_scenarios.py agent/tests/unit/test_context_facts.py agent/tests/unit/test_context_citation_survival.py agent/tests/unit/test_context_trimming_demo.py agent/tests/unit/test_observation_read.py agent/tests/unit/test_live_model_client.py agent/tests/unit/test_harness_manifest.py agent/tests/unit/test_deepseek_config.py agent/tests/unit/test_reviewer_live_check.py agent/tests/unit/test_reviewer_demo_driver.py agent/tests/unit/test_action_repair_notice.py agent/tests/unit/test_harness_loop.py agent/tests/integration/test_deployment_factory.py agent/tests/integration/test_observation_read_loop.py agent/tests/integration/test_sdk_durable_recovery.py agent/tests/integration/test_reviewer_diagnostics.py agent/tests/integration/test_reviewer_input.py agent/tests/integration/test_context_wiring.py -q
pnpm --dir web test --run
pnpm --dir web build
.\demo.ps1 -Live -SkipBuild -NoBrowser
```

本次迭代共记录 **57 个已保存成功响应，输入 92,173 tokens、输出 15,884 tokens**；另有 **2 次 HTTP 400**（其中一次是手工诊断），合计 59 次已知请求。统计来自供应商成功响应 usage，不等同于账户账单。19 个运行涉及不同提示词/代码版本和材料修订，包含格式、引用与上下文预算失败；不能把它们当作固定版本的成功率测评。失败没有绕过人工或退款硬约束生成付款许可。

未运行：全仓历史矩阵、5 个已知过期 `test_committed_golden_pack`、移动端专项和用户侧网页验收。旧回放包没有为通过检查而重录或改断言。本轮相关测试通过不等于全仓所有测试均通过。

## 交付边界

审查侧当前具备可演示的“接收申诉与原始材料 → Agent/RAG 建议和可追溯依据 → 补证/核验后重新调查 → 人工批准、拒绝或继续补证 → 模拟执行结果”闭环。人工接管可处理没有有效 Agent 建议的工单。

模型语义判断仍可能不准确，真实样例也会走人工复核或受控失败；没有承诺建议百分之百正确。保护层放不下的超大上下文会明确失败而不丢关键事实。现有材料以保存的陈述/记录为依据，没有新增图片真实性检测引擎。退款仍是范围内的单订单行全量模拟退款，不能用于真实支付；用户侧产品改造留待用户确定。
