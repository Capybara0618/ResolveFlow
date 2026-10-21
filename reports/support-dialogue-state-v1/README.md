# 客服对话变化与跨轮陈述记忆

2026-10-21。本批实现已经完成，正式模型效果评测尚未运行。[设计](../../docs/customer-dialogue-state-v1.md) / [结构化记录](completion.json)。

## 已实现的行为

| 能力 | 本批实现 | 示例 |
| --- | --- | --- |
| 理解本轮变化 | 同次模型动作输出任务及 ADD / CONTINUE / CORRECT / CANCEL / PAUSE / RESUME / CLARIFY，不增加分类请求 | 用户“先问退款入口，签收核查稍后继续”对应暂停核查、新增入口问题 |
| 任务连续性 | SUSPENDED 跨轮保留；未完成任务不能静默消失，暂停与取消分开，恢复须 RESUME | 用户“继续签收核查”恢复原任务 |
| 有效陈述记忆 | 记录客户原话、消息序号、Unicode 字符偏移、主题及稳定 id | “家人可能代收了”可在旧历史被裁剪后继续可见 |
| 纠正与撤回 | 新条目显式关联旧条目，原话不覆盖；无明确替代关系的冲突并列 | “纠正：家人没代收”替代旧猜测；找到包裹后可撤回核查任务 |
| 跨轮保存 | Java 从同会话最新成功结果冻结陈述，Python 加载到本轮受保护上下文 | 下一次客户消息继续获得当前有效信息 |
| 原文可回查 | 当前输入或已读取的客户历史才可作为来源；Java 发布/冻结时再回查原消息 | 带 emoji 的字符定位一致，不把助手原话当客户陈述 |
| 恢复 | 已保存的决策按原 manifest / 输入重建任务、事件和陈述状态 | 隔离 PG 恢复探针没有新增模型或上游调用 |

仍为单 AgentScope 循环：客户消息与历史、上一轮未完成任务、有效陈述、可信业务状态和工具观察进入预算化请求 → 模型同时标注诉求/变化/陈述并选择行动 → Harness 校验后原子更新 → 读取工具或回答 → 既有 run 结果保存 → Java 冻结给下一轮。RAG 仍是按需工具，本批没有改检索算法。

客户陈述与模型任务标注均不等于系统事实。金额、物流状态、工单进度仍由业务读取提供；旧 run 的 O/P 引用不作为本轮证据复用。内部状态保存在现有 answer 开放对象，不增加表或公共客户端字段，客户消息投影不暴露记忆对象；商家共享流程沿用原实现。

## 实际验证

- Python：20 个相关文件共 **113 通过、0 失败、0 跳过**。包含 14 项陈述测试、6 项对话变化测试，以及实际 ASGI → SupportRuntime → AgentScope → 隔离 PG 的四轮脚本。生成模型与业务 HTTP 使用明确合成桩，不能当真实模型质量成绩。
- 四轮脚本：核查签收 → 插问入口并暂停 → 恢复及纠正 → 找到包裹并取消；脚本模型调用数依次 2/2/2/1。重复派发结果相同；最后一轮模拟持久调用完成但 finish 丢失，按相同 manifest 恢复，新增模型/上游调用均为 0。
- Java：真实隔离 MySQL/HTTP 的 SupportApiTest **16** 项、SupportWireTest **2** 项通过，0 失败/错误/跳过。新增用例覆盖同商品跨轮加载、其他商品隔离、emoji 原文偏移和内部字段不进入客户投影。没有运行 Java/Python/浏览器同时在线的完整演示。
- 8 个相关生产模块 strict mypy、相关 Ruff、两个自有 Java 文件定点 Spotless apply、git diff 检查通过。保留 Starlette 的原弃用警告，不宣称全仓测试通过。
- 新真实模型请求 **0**，使用账本仍 1540。保留 PG 的 11 张 public 表前后全行 hash 与上批 v3 相同，自有临时 schema 为空；原四历史脏文件字节 hash 保持。PG 已停止、卷保留，10 个项目端口关闭。

### 命令

在 agent 目录，设置 `RESOLVEFLOW_AGENT_DB=postgresql://agent:agent@127.0.0.1:55433/agent_db` 和 `PYTHONPATH=E:/Code/Agent+Backend` 后实际执行：

```powershell
.venv/Scripts/python.exe -m pytest tests/unit/test_customer_agent_live_v3.py tests/unit/test_customer_rag_live_v2.py tests/integration/test_customer_rag_live_v2.py tests/unit/test_support_agent.py tests/unit/test_support_guidance.py tests/unit/test_support_recovery.py tests/unit/test_support_guide.py tests/unit/test_support_sources.py tests/unit/test_support_retrieval.py tests/unit/test_support_api.py tests/unit/test_contracts_support.py tests/unit/test_contracts_support_agent.py tests/unit/test_support_tasks.py tests/unit/test_support_context.py tests/unit/test_support_memory.py tests/unit/test_support_dialogue.py tests/integration/test_support_store.py tests/integration/test_support_retrieval_index.py tests/integration/test_support_guide_api.py tests/integration/test_support_dialogue_api.py -q
.venv/Scripts/python.exe -m mypy --strict src/resolveflow/support/memory.py src/resolveflow/support/dialogue.py src/resolveflow/support/engine.py src/resolveflow/support/protocol.py src/resolveflow/support/guidance.py src/resolveflow/support/service.py src/resolveflow/support/tasks.py src/resolveflow/support/context.py
.venv/Scripts/python.exe -m ruff check src/resolveflow/support/memory.py src/resolveflow/support/dialogue.py src/resolveflow/support/engine.py src/resolveflow/support/protocol.py src/resolveflow/support/guidance.py src/resolveflow/support/service.py tests/unit/test_support_memory.py tests/unit/test_support_dialogue.py tests/integration/test_support_dialogue_api.py
```

在 java 目录，使用 JDK 21：

```powershell
.\mvnw.cmd -pl case-service -am '-Dtest=SupportApiTest,SupportWireTest' '-Dsurefire.failIfNoSpecifiedTests=false' test -q
.\mvnw.cmd -pl case-service '-DspotlessFiles=.*SupportAgentTurns[.]java' spotless:apply -q
.\mvnw.cmd -pl case-service '-DspotlessFiles=.*SupportApiTest[.]java' spotless:apply -q
```

### 开发失败与修正

来源化陈述先有 7 项红测；首次回归因请求内容增加使旧 guide 测试窗口超限，精简重复系统提示后相关 47 项通过，没有扩大窗口。对话变化先有 5 项红测；旧 task 字段反馈优先级出现 1 项失败，恢复先任务字段校验、仍整体原子提交后相关 52 项通过，另补旧消息不能授权当前撤回的用例。

跨轮 Java 新用例先失败，接线后 18 项通过。恢复探针首版换了 mock 脚本而触发 MANIFEST_MISMATCH；保留原 manifest 的正确恢复探针通过。上述是实现过程失败，不是正式效果测量失败。Java 日志本机保存在 `tmp/support-dialogue-java-red.log`、`tmp/support-dialogue-java-green.log`，数据保持见证在 `tmp/support-dialogue-state-v1/preservation.json`，不提交原始日志或数据库快照。

## 当前限制与评测边界

程序校验引用确实存在及状态/链接是否一致，无法由此证明模型对“这是纠正还是补充”的语义判断正确。记忆依赖模型选择要保留的客户陈述，可能漏记或误关联；任务和事件同样仍需真实多轮评测。没有加入额外 LLM 摘要、关键词分类路由、跨商品长期画像或自动归档层。

当前最多 12 条有效陈述、24 条总陈述；超限给出明确反馈，不能静默删除有效信息。有效条目在历史裁剪外保留，但仍受总请求窗口限制，超限不会假称成功。这是当前个人项目的有界实现，长会话归档策略仍可在后续依据实际样本决定。

旧 `customer-agent-readiness-v1` 清单绑定旧源码；本批改动后旧预检应拒绝 hash 不匹配，已经用新测试验证其拒绝。未覆盖或删除旧 4 项预检单测和 1 项旧 API 就绪测试，也未将它们计入本批 113 项通过；原 36 轮问题、Gold、旧清单和历史报告保持。后续正式评测需新冻结版本，再测真实意图/变化判断、纠正后回答一致性、多事项完成率、请求成本和延迟。

未改简历或前端，未运行收费效果评测，未重复旧退款回归。工程机制完成不代表这些真实效果指标已经改善。
