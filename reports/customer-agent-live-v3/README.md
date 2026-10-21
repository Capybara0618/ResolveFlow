# 客服Agent/Harness优化与真实模型回归 v3

2026-10-21。按[本批方案](../../docs/customer-agent-optimization-v1.md)完成工具协议、具体纠错、来源故障状态和可信会话状态接线，并在同一组12个业务输入上执行一次新真实模型回归。业务完整满足从6/12到11/12，仍有P03条件遗漏，不能称所有客服能力完成。

## 实现了什么

1. `guidance.py`提供实际模型可见的工具目录，与SDK共用用途/参数。明确订单/物流事实、商家退款资格、平台操作指南各自负责什么；JSON动作示例不再把多个工具用“或”写进同一tool_name。仍由模型选择工具，没有关键词路由、固定全量流程或第二循环。
2. 错误动作的一次纠错反馈给出kind/schema字段及合法形状；不存在的引用列出本run合法编号。没有静默把模型错误改成执行动作，也没有新增未记账调用。合法SDK参数schema同步，当前生成模型仍沿用结构化JSON动作模式，不宣称已改原生function calling。
3. `SourceRecovery`记录工具及参数的失败次数/可重试性，实际请求携带source_status。可重试错误至多访问两次，不可重试错误不再外部访问；再次选择被阻断动作会记录明确错误并继续计尝试，由模型选择说明缺失、读指南或整理待客户确认的核查摘要。总预算/NO_PROGRESS仍兜底，没有自动商家接管或伪造业务答案。恢复从已持久工具响应重建状态，不清零或重发缓存调用。
4. Java在会话版本/fence检查后的短事务中冻结has_ticket、ticket_status、current_recipient和default_recipient。Python将它们与客户陈述分别传给模型，旧输入缺失为null。当前消息私发助手不等于页面默认对象也是助手。未改金额、审批、退款工具或原调查循环。
5. 合并重复系统提示，要求使用合适来源、回应混合问题、保留决定性条件/事件/例外。模型指南仍有完整正文和authority，逐篇审计元数据留在持久来源/最终引用。确定性检查继续负责结构、引用存在和实际来源范围，不能证明任意自然语言答案完整；本轮P03即为剩余反例。

独立已验证小步普通push核实：工具与纠错`d968a99`、故障状态与恢复`88a100c`、可信会话状态`9637b4c`；真实回归准备`fc0c794`。

## 验证口径

[冻结新输入](../../evals/customer-agent-live-v3/cases.json)与v2逐字段比较，客户问题、历史、商品/订单/物流合成快照、政策generation、预期工具能力和每项3条业务标准都不改；只更换run/conversation身份，不能用新源码恢复旧run。绑定旧两份结果及语义源审hash。每项新版本只执行一次，不重跑挑选答案。

真实DeepSeek Flash、生产Python ASGI→SupportRuntime→AgentScope→真实BGE/只读保留PG政策；订单/物流HTTP仍是冻结合成响应，F02实际返回503。run/call只写自有临时schema，业务服务/worker未启动。这不是Java/浏览器同时运行的全栈验收，亦非真实用户数据或独立盲测。

新可信会话状态没有补造到旧快照，本轮真实回归中为null，接线由独立Java/Python测试证明。不能把回归改善归因于新状态字段。模型/检索/依赖锁不变，但供应商模型不确定性、时点/缓存和组合修改使本轮只能作为开发集版本回归，不能分别宣称每个组件的因果提升或泛化准确率。

## 实际结果

| 指标 | 改前v2 | 本轮v3 |
| --- | ---: | ---: |
| 生成答案 | 10/12 | 12/12 |
| 完整满足原业务条件 | 6/12 | 11/12 |
| 部分满足 / 失败 | 3 / 3 | 1 / 0 |
| 政策场景必要规则覆盖 | 5/5 | 5/5 |
| 需要指南的场景实际读取 | 2/7 | 7/7 |
| 模型请求 / 实际工具执行 | 30 / 16 | 28 / 16 |
| 政策检索行动 | 6 | 5 |

G01人工咨询、G03私有消息切换、G04退款入口、F02故障交接、M01混合问题由不完整/失败变为完整；原6个通过项保留，没有原通过项退化。来源检查与[逐项语义复核](semantic-review.json)记录原标准、引用、判定和原因；[对照](comparison.json)绑定旧结果，未改旧评分。

F02这次选择“查物流→读指南→再查物流→回答”，两次503后说明暂不可用而非丢失/未发货，并给客户自行确认的商家核查步骤，没有假称已转交或退款。实际生成模型未选择第三次查询，因此外部阻断/恢复的正确性仍以脚本和真实隔离PG测试为证，不把未触发门禁算成已触发。

P03仍为部分通过：在途/未发货两条必要政策都存在，但答案只说已付款且明确NOT_SHIPPED，遗漏版本1和ORDER_PAID事件条件；并在没有读取实时物流时把“未见承运商异常/其他经核验理由”说成当前情况。属于生成使用依据不足，未通过修改政策或正则补词掩盖。原固定口语P02 Query的历史漏召回也没有据本轮新Query成功而被宣布修好。

G02把原文/依据勾选说成在“转交摘要中”，仍有控件措辞不够精确；与旧版相同标准记文字改进项。G04/M01直接复述指南中的“Case关联尚未接通”等内部术语，虽满足原业务标准，面向客户的表达还应简化。答案更完整不等于措辞已最佳。

## 时间与token

12项完整Python接口（包括记录开销、排除预热、不含Java/浏览器）中位2.686秒、描述性P95约4.974秒，范围1.990–5.315秒。改前中位2.759秒/P95约5.006秒，差距很小，不能宣称稳定提速。5次政策检索中位61.3ms/P95约106.4ms，第一条115.3ms，其余46.1–70.5ms；不是吞吐或SLA。预热10.84秒单列。

28次调用均为provider实际usage，输入42,230、输出2,117 token；改前35,207/1,848，因此输入约增加19.9%、输出约增加14.6%。需要指南的问题现在正确带入正文，不能因为模型请求减少2次就说token或费用降低。保留原累计ledger1512→1540，无新累计消费上限、无重置历史；未按未经核验单价换算费用。模型往返总33.47秒/接口总36.27秒仅本组观察。

## 工程验证和开发失败

- Python咨询/新目录与纠错/故障变体/协议/检索/ASGI/隔离PG恢复/评测驱动集中77通过，0失败/跳过；4修改生产模块严格mypy通过，相关Ruff通过。新失败读取、稍后恢复、不可重试和崩溃复用分别测试。
- Java JDK21、隔离Testcontainers MySQL/真实HTTP，SupportApiTest14 + SupportWireTest2 =16通过，0失败/错误/跳过。两个自有Java文件Spotless apply通过；未改前端组件和原退款测试，不重复整仓构建或已知旧调查3失败。
- 初始工具目录/精确反馈3关键红测失败；接线后20通过/1指南窗口溢出，合并重复提示与审计元数据后21通过，窗口/预算未扩大。故障状态3红测失败后通过，可信状态Python红测1失败后通过。
- Java首次14中1失败；接线后测试误将派发JsonNode转成Map，异常被派发重试处理捕获，仍1失败。改用实际JsonNode，并在派发外检查持久状态和TEST_ONLY原因，防止被捕获异常导致假通过，最终16通过。原Starlette/Mockito警告保留。
- 从agent目录检查根scripts导致Ruff导入分类2告警，统一仓库根配置检查并修正新测试导入后通过，未为此重排原脚本。无新权重/依赖安装；旧4个历史脏文件hash保持。

复现工程验证在agent目录运行下列pytest（仓库根加入PYTHONPATH、保留PG55433可用），以及mypy/Ruff：

```powershell
.venv/Scripts/python.exe -m pytest tests/unit/test_customer_agent_live_v3.py tests/unit/test_customer_rag_live_v2.py tests/integration/test_customer_rag_live_v2.py tests/unit/test_support_agent.py tests/unit/test_support_guidance.py tests/unit/test_support_recovery.py tests/unit/test_support_guide.py tests/unit/test_support_sources.py tests/unit/test_support_retrieval.py tests/unit/test_support_api.py tests/unit/test_contracts_support.py tests/unit/test_contracts_support_agent.py tests/integration/test_support_store.py tests/integration/test_support_retrieval_index.py tests/integration/test_support_guide_api.py -q
```

Java在java目录执行`mvnw.cmd -pl case-service -am -Dtest=SupportApiTest,SupportWireTest -Dsurefire.failIfNoSpecifiedTests=false test -q`。真实结果已完成，驱动拒绝覆写；正式命令`customer_agent_live_v3.py --execute --output ...`只作本次来源说明，不自动重复付费。后续新实验要另冻结范围。

## 收口与剩余工作

本批Agent优化和一次真实回归完成，尚不能保证所有政策条件/自然语言事实完整。下一项值得处理的是P03这类生成遗漏和客户/系统事实表述，另有客户措辞简化；不默认继续收费调参或更换模型框架。

原public11表before/after全行hash相同，临时run/call已导出、自有schema清理、原数据卷保留；收口状态见[完成记录](completion.json)。当前普通业务服务保持关闭，下次正常启动加载新代码，不消费旧队列或重算历史run。
