# 第四批：五个难例的Agent/RAG诊断与必要修复

先读[总约束](README.md)。目标是找出具体失败并修对应层，不是全面重建Agent/RAG。前提：第二批整链路和第三批依据阅读已可演示。

## 1. 模式与完成边界

默认只做离线。DS作为编码模型的使用授权不等于允许项目内Agent调用收费API；用户尚未授权新live模型/总预算，禁止使用旧C12额度。真实模型供应商、model id、调用上限、总金额上限必须由用户明确给定，执行者不能从“DeepSeek v4.1flash”这个编码执行名称猜业务模型配置。

本批区分三份结果：规则/数据隔离验证；mock上下文与接线验证；live建议质量（未授权则NOT_RUN）。前两份通过可进入第五批，不能声称真实模型质量改善。不要反复向用户询问预算。

## 2. 先读的具体入口

| 层 | 代码 | 验证入口 |
| --- | --- | --- |
| 政策分块与索引 | `agent/src/resolveflow/policies/chunking.py`、`index.py`、`retrieval.py` | `test_policy_chunking.py`、`test_policy_index.py`、`test_policy_search_action.py` |
| 上下文与提示词 | `agent/src/resolveflow/harness/context.py`、`vocabulary.py` 的HARNESS_SYSTEM_PROMPT | `test_context_builder.py`、`test_context_facts.py`、`test_context_scenarios.py` |
| 结构化决策和引用 | `agent/src/resolveflow/harness/actions.py`、`sdk_runner.py` | `test_reviewer_findings.py`、`test_investigation_loop.py` |
| 生产装配与恢复 | `agent/src/resolveflow/runtime/factory.py`、`durable.py` | `test_deployment_factory.py`、`test_sdk_durable_recovery.py` |
| 现有检索评估 | `scripts/policy_search_eval.py`、`scripts/policy_index_ingest.py` | 先看help/源码及环境，禁止直接恢复旧矩阵 |

上述test文件用 `rg --files agent/tests` 找实际unit/integration位置。专题仅按需读 `docs/policy-rag.md`、`docs/context-engineering.md`、`docs/agent-harness.md`、`docs/trajectory-replay.md`。

## 3. 子步A：固定五个诊断场景

建议新增 `agent/tests/fixtures/reviewer_diagnostics.json` 和一个定向测试文件（均为待创建），记录为诊断集，不冒充冻结test或总体效果基准。复用第二批数据形状，测试数据独立，不修改演示样本。

| 场景 | 给定材料 | 必须满足 | 不允许 |
| --- | --- | --- | --- |
| 签收冲突 | 客户未收到；物流SIGNED、有效签收记录；无LOST确认 | 两来源与版本进入上下文；可提出签收争议的具体补证或转人工；输出注明冲突 | 把客户说法写成承运商确认丢失；执行丢失退款 |
| 单方损坏 | 客户声称损坏，未有人工核验 | 说明缺少核验；按现有规则补证/转人工；材料改变后旧修订失效 | 虚构图片鉴定、核验人或自动确认真实 |
| 无适用政策 | 当前manifest无匹配规则，或索引未READY | 将无命中与索引未就绪分开；明确缺依据/服务问题 | 换商户/换最新bundle，随便引用最高分条款 |
| 政策例外 | 政策为“LOST且无有效签收才可退款”，材料包含例外触发事实 | 分块、检索结果、上下文保留完整条件/例外；建议不能忽略例外 | 截出“可退款”后当成充分依据 |
| 针对性追问 | 缺具体一项影响判断的材料，部分问题已答 | 提问对应明确缺口，带稳定question_id；已有回答不重复索取；两轮/超时有效 | 泛泛“补充更多信息”、无穷追问或改写旧答案 |

每例记录：case facts、policy bundle/version/manifest、预期允许动作集合、禁止结果、期望保留的来源字段、实际结果、模式和测试证据。允许不同合法工具次序，不断言唯一完整路径。

## 4. 子步B：诊断顺序与修改边界

每例依次检查：

1. **工具数据**：原记录本来有无关键字段、时间、来源？没有则修合成fixture或对应实际投影，不让提示词补造数据。
2. **检索**：主体、bundle/version、manifest与READY是否正确？命中段落是否含例外？先修过滤/切块，再考虑排序；不得为提高命中放宽过滤。索引更新用新generation/既有流程，不改历史run绑定manifest。
3. **上下文**：关键事实、来源、冲突、已回答问题是否在真实组装请求里？检查裁剪后packet，而非仅看中间对象。修保留/裁剪优先级，不全量塞回原文或调大预算。
4. **建议输出**：ABI、review_findings与引用是否对应真实输入？缺少来源按既有校验拒绝或明确不可执行。不得为了新样本允许模型任意造hash。
5. **只有确有提示词问题**才微调vocabulary.py：要求保留条件例外、标出缺口、具体追问，不能写“看到SIGNED先调用工具X再Y”的固定全路径。不写样本ID/预期答案触发器。

默认不改sdk_runner完整循环、run所有权、预算/恢复。若确需修改ABI或上下文格式，同步契约、类型、fixture、请求追踪/hash和消费者，给出兼容解释。改提示词后只用于新run；旧run恢复不能静默换prompt/manifest。

明确禁止：增加hybrid/RRF/rerank、换embedding/依赖锁、新多Agent、模型路由平台、删除失败样本、反复在冻结test上调参。五例全过且无真实缺口时交付诊断结果，不为“优化”制造代码改动。

## 5. 子步C：验证方式

mock能证明数据、结构、限制和保存链路，不能证明模型自主识别冲突。尽量让测试断言实际context packet包含关键来源/例外、裁剪后仍保留，不只断言一段固定mock字符串等于预设答案。

对检索过滤可以用stub_embedder与真实PG；质量对比需要同一已缓存真实embedding、同样本/语料/参数的改前改后结果。缺模型缓存则报告真实dense评估未运行，不用stub分数替代。样本量小只能逐例报告，不外推正确率提升。改前结果在改动前保存，不事后补写。

```powershell
agent/.venv/Scripts/python.exe -m pytest agent/tests/unit/test_policy_chunking.py agent/tests/unit/test_reviewer_findings.py agent/tests/unit/test_context_builder.py agent/tests/unit/test_context_facts.py agent/tests/unit/test_context_scenarios.py -q
agent/.venv/Scripts/python.exe -m pytest agent/tests/integration/test_policy_index.py agent/tests/integration/test_policy_search_action.py agent/tests/integration/test_context_wiring.py -q
```

加入新诊断测试的真实文件路径。仅变动循环/持久请求/恢复时增加 `agent/tests/integration/test_sdk_durable_recovery.py`、`test_recovery_budget_store.py` 和受影响strict回放测试；不能以旧LangGraph通过代替AgentScope。Java规则未变不跑全仓Java。

后续若用户授权live：只对五例新run执行，固定模型和manifest，调用前设总金额/调用/时间上限、失败也计费用，记录请求hash、引用、token、耗时和未知计费情况；无计费上限控制不启动。live失败按上述诊断顺序修，不扩大矩阵；严禁strict回放联网。

## 6. 交付

`reports/reviewer-agent-rag.md` 必须逐例列“预期/改前/原因/修改/改后/证据/模式”，另列真实模型NOT_RUN原因及真实dense是否运行。若没有变更也给出为何已有实现满足离线要求。todo应写“第四批离线工程部分完成，live待授权/验证”而非“模型质量已优化通过”。相关测试无新增失败才提交并继续第五批。
