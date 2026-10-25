# 独立 Workflow 对照：设计与离线准备

2026-10-25，用户要求开始设计，独立基础Workflow不得借用现有Agent内部模块。本轮完成[可执行规格](../../docs/customer-workflow-comparison-v2.md)、[32场景/50输入的对外判据](../../evals/customer-workflow-comparison-v2/cases.json)及[离线审计/源审模板/主指标汇总入口](../../scripts/customer_workflow_comparison_prepare.py)。基线业务实现、真实执行器和Agent修复尚未做；没有正式效果分数。

主对照是完整客服Agent与“原始历史→LLM路由→固定分支→LLM回答/摘要”的独立Workflow。只共用模型API、主体绑定、订单/物流/政策/指南原始接口和中性测量设施；不共用理解、事项、记忆、Harness、来源就绪、摘要装配或生产提示词。普通分支覆盖ORDER/LOGISTICS/QUALITY/POLICY/REFUND/HANDOFF/GUIDE及OTHER，必须先实际可用；最终回答允许覆盖已有依据支持的多个问题。

主指标是24个复杂模拟售后场景的完整处理成功率，普通8个和总体32个分别列出；首次仅一轮配对，64会话/100客服轮。模型/工具/时间成本辅助报告，不预先承诺每项都优于基线。相同客户原话和事实，输出改用对外业务判据；不检查Agent专用状态。Q25条件句允许解释假设，不强制查询，两边同标准。旧v1负向结果保持，新比较不能与旧分数拼接；不是独立盲测。

实际命令（仓库根，现有agent/.venv，PYTHONPATH为仓库及agent/src）：

```powershell
python -m scripts.customer_workflow_comparison_prepare audit --output reports/customer-workflow-comparison-v2/design-audit.json
python -m pytest agent/tests/unit/test_customer_workflow_comparison_prepare.py -q
python -m ruff check scripts/customer_workflow_comparison_prepare.py agent/tests/unit/test_customer_workflow_comparison_prepare.py
```

[数据审计](design-audit.json)通过：32场景、24复杂、50原输入、源快照/顺序/故障覆盖与v1相同。10项离线检查通过，Ruff通过。首次9项中空格摘要被误当存在（1失败/8通过），补为非空文本后9通过；随后新增旧协议/异数据身份检查，最终10通过。脚本数据只证明准备/评分器接线，不是Workflow或Agent质量。

已验证：无需task_state/记忆标记也可按相同业务结果评分；缺摘要、错误操作摘要、技术失败勾全通过、未审、缺结果、身份不符均拒绝；失败成本/超时/NOT_RUN保留分母，任一轮失败整会话未完成。源审依赖Codex读取原话/实际来源与回答，不按关键词自动判语义。

后续中性runtime文件准备好后可运行`review-template --runtime 新文件 --output 新源审.json`，填三项检查/evidence后运行`summarize --runtime 新文件 --review 新源审.json --output 新汇总.json`。CLI绑定完整runtime字节hash，输出拒绝覆盖。主指标汇总已实现；耗时分位数、真实usage/未知usage、双方均完成的调用配对分析由后续执行/报告接线完成，不假称本轮已测量。

下一实施步是独立基线及其普通分支/异常出口/草稿的离线接线验收；随后另做Agent通用缺口修复和双组执行器。待实现固定后再生成执行manifest，不能把设计审计称为正式冻结。预计约250模型请求、建议上限400仅作后续计划，当前未发送且未授权执行本批测量。

本轮新供应商/本地模型推理0，ledger3053保持；未访问业务数据库、未启停服务、未改生产/简历。旧报告、旧manifest/数据、四历史脏文件保持，保留核验见[本轮审计](preservation-audit.json)。现有RAG正式结果独立保留，不因新Agent基线自动重测。

## 独立控制器实现（2026-10-25接续）

独立模块scripts/evaluation/basic_customer_workflow.py已实现：八类单意图路由、固定读取、一次公共GUIDE、最多两次模型常规调用、每阶段一次格式修正、瞬态源失败重试一次及最终失败说明、直接模型草稿输出。无跨轮结构化状态、无自选追加工具、无Agent继承/生产提示/grounding/确定性摘要装配；导入隔离检查只允许标准库与pydantic。按主体读取的客户端仍由后续中性服务提供，控制器本身不持有业务写入口。

实际`pytest agent/tests/unit/test_basic_customer_workflow.py agent/tests/unit/test_customer_workflow_comparison_prepare.py -q`为27通过（17基线+10准备），四文件Ruff通过。先测试确认模块缺失的收集错误，落实现后全部通过；首次Ruff的导入/行长及异常边界说明已修。覆盖八分支、草稿原样保留/不补写缺稿、503两次原始结果进回答、404不重试/不拿标价代实付、最近20条原始历史/过滤Gold及Agent状态、格式修正不重新取证、模型不能追加工具、预算/超时停止、异常调用的未知usage留痕。

[八分支脚本接线](basic-workflow-offline.json)及[当前准备审计](baseline-audit.json)已生成，全部mode=scripted，不是业务质量分数或真实分类成功率。一次命令把烟测代码传给audit模块的stdin，实际只执行审计；已用独立Python stdin入口真正运行八分支并保存输出，未产生供应商请求。普通首正文尚未独立流式计时，first_body_ms=null/NOT_MEASURED，不填0。

本步0新供应商/本地推理、ledger3053；无DB或服务启停、无生产/简历改动。真实模型客户端、共享原始接口/两组历史驱动及性能聚合仍待接线；Agent通用缺口接下一小步。设计阶段design-audit/preservation-audit保留原时间状态，不回写为已经实现。

## Agent批量只读合同修复（2026-10-25接续）

根因是把“当前回答必须有哪些依据”误当成“模型只读权限”，且优化动作READ_FACTS要求恰好两个事实工具，导致物流+政策、订单+政策等合理组合被拒绝。现允许1–2个不同绑定事实工具加可选政策query，总读取至少2项；未列needs的相关只读也与单项READ_TOOL权限一致，不静默替模型删工具/query或补语义。仍只允许订单/物流与search_policy，禁止额外主体、参数、写入口和重复事实工具；每子项仍走原execute的scope/fence/预算/失败重试/journal。提示说明按观察选组合，不固定全量路径。

先4红/20通过→24针对通过；扩大实际命令为`pytest`全部test_support_*.py，521通过。原55433 PG运行test_support_fact_batch_runtime、test_support_evidence_batch_runtime、test_support_orchestrated_runtime、test_support_goal_review_runtime、test_support_boundary_closeout_runtime，共13通过；新增单事实+政策的实际持久化与同run恢复0新调用，原部分恢复/预算/fence断言保留。六文件Ruff通过，只有已有Starlette弃用警告。

两个旧“未声明需要就拒绝批量读取”的测试按新权限一致性合同更新，改为验证实际调用/费用/模型不触发修正，未删除重复/越主体/写工具/预算/未落库重发等失败断言。[旧真实输出的合同检查](batch-contract-check.json)覆盖11个失败轮/22个保存批量决策，全部新形状合法；它不是完整对话回放，也没有新模型回答。Q22-r2终局多字段失败之前同样发生过batch拒绝，但不能据此提前宣称其发布已修复。

原public11表前后hash一致，临时测试schema清理，ledger3053不增；未重启业务或消费旧run。生产三文件有意变化，v1旧源码manifest不再匹配当前工作区，保持旧manifest/结果不重写，新执行入口需另建manifest。政策遗漏/条件当事实/人工摘要等业务质量须新对照源审确认，不以解析通过冒充成功。一次只读rg通配路径和不存在历史测试名查找失败，已定位实际文件，不影响测试执行。

## 中性源服务与独立模型传输（2026-10-25接续）

新增scripts/evaluation/customer_comparison_environment.py，不导入生产Agent。PlainChatClient直接使用httpx/SSE，固定DeepSeek Flash/temperature0/非thinking/JSON；与Agent只共享API及原始资源。RequestAllowance在发送前持久化实际尝试数，失败仍计费计数、发送前额度拦截另记未发送；未知usage不估算。GUIDE独立读取已版本化公共原文，订单/物流mock只返回冻结HTTP状态/原始体，拒绝跨run/写入口；历史只返回要求之前的原文。

RawPolicyService只验证当前主体/manifest/固定generation后调用索引的small_context返回完整原文，超出小集合明确失败，不替基线增加Query改写或Agent模块。[原PG只读核验](environment-check.json)确认32场景均六条，逐条与生产BoundSources相同，GUIDE相同，public11表前后相同。该脚本位于忽略的tmp/customer-workflow-comparison-v2/check_environment.py；可复用check命令会在下一步双组入口提供。

实际`pytest agent/tests/unit/test_customer_comparison_environment.py agent/tests/unit/test_basic_customer_workflow.py agent/tests/unit/test_customer_workflow_comparison_prepare.py -q`为44通过（15环境+19基线+10准备）；四文件Ruff通过。先模块缺失收集失败，落实现后通过；Ruff导入/循环lambda捕获两项修正后通过。含SSE真实usage/未知usage/连接失败/额度发送拦截、正文JSON前缀/半转义解析、截断及length结束拒绝发布、最终保留正文计时、原始故障/原文分页/主体与generation隔离。首正文计时是服务端JSON可见text，格式修正被丢弃的回答不算保留正文，尚未测真实耗时或页面速度。

首次PG核验连接池超时，核实原容器2697eb86cf0b已Exited且55433无监听，执行docker start原容器后只读核验成功；原卷resolveflow-review-demo_demo-postgres-data保留，无端口改动/清库/Java或前端启停。0供应商/本地模型、ledger3053；新客户端只用HTTP桩测试，未验证供应商当前网络。双组驱动及性能聚合接下一步，不称正式可执行已冻结。

## 双组执行与性能汇总（2026-10-25接续）

新增scripts/customer_workflow_comparison_live.py，Agent组直接运行当前生产SupportRuntime/AgentScope；Workflow组直接运行独立控制器/httpx。不继承Agent构造基线、不patch生产理解/调查/回答逻辑；只替换冻结HTTP源与接收进度的传输。分别保留实际对话原文及草稿，失败不虚构助手回答；Agent按原机制继承实际已接受的状态，Workflow无状态。Gold/评语不进两组模型；32场景交替两组先后，每个场景各组依序进行全部轮次，共64会话/100轮。

实际固定DeepSeek Flash、temperature0、非thinking/JSON、32768容量、8192输入、1024输出、12模型/120秒。输入计数是共享官方tokenizer原始资产的独立计量实现，已比较与Agent计数一致，不导入Agent上下文逻辑；两边计时前预热。每轮保留实际请求body、usage、原始结果/工具结果、流式事件与首正文时间；草稿仅字段映射，不补内容。Agent进度投影的保留正文与Workflow的有效JSON text均为服务端时间，不能写成浏览器实测速度。

prepare汇总新增真实发送计数、被拦截调用、已知/估算/未知usage、首正文及最终时间P50/P95（NEAREST_RANK，附n）、全量业务HTTP和双方均成功配对成本。失败成本全部保留；未运行仍计主指标分母，但不能填0耗时或虚构请求。实际业务评分仍逐轮源审，三个布尔判据+证据完整后才出完整处理率，不用技术SUCCEEDED替代业务正确。

实际命令：`pytest agent/tests/unit/test_customer_workflow_comparison_prepare.py agent/tests/unit/test_customer_workflow_comparison_live.py agent/tests/unit/test_customer_comparison_environment.py agent/tests/unit/test_basic_customer_workflow.py agent/tests/integration/test_customer_workflow_comparison_live.py -q`，56通过（12准备+5驱动+17环境+19基线+3PG集成），九文件Ruff通过。PG使用原55433：两轮两组真实SDK/PG/SSE桩成功、独立历史不串、真实请求输出上限1024、首正文可测，同run用原输入快照恢复不产生新请求。完整execute分别在1/3次桩请求上限停止，99/98轮NOT_RUN保留100分母，provider次数准确且无凭据入输出，实际run/call导出后清理自有schema，public保持；不是新质量分数。

测试过程中先模块缺失收集失败；独立矩阵测试datetime序列化修正；第二轮测试脚本错误ADD与旧事项冲突后改CONTINUE；恢复测试重建deadline触发INPUT_MISMATCH后改用原持久输入，没有放松生产fence/输入合同。性能新增关键检查先3失败/9通过，补实现后通过；Ruff导入/行长修正。一次全驱动测试对transport=None使用setdefault没覆盖，Agent持测试假凭据尝试供应商并被ModelRefusedError拒绝（非有效账号生成，无法确认具体HTTP码）；修复为显式覆盖None，随后1/3上限测试全部由MockTransport接管。该次拒绝网络尝试1单列，不能宣称绝对零网络；真实计费账本仍3053，没有使用有效凭据的新生成或付费评测。

[驱动预检](driver-preflight.json)已通过原PG32场景/每场景六政策/public一致（当时尚未冻结，manifest_checked=false）；[当前审计](driver-audit.json)记录基线及Live执行器已实现、质量未测。旧设计审计、旧正式128会话/600检索及负向结论不回写。下一步仅完成新manifest冻结核验和保留审计，再等待正式测量要求；既有RAG对照独立保留，不自动重跑检索或选择有利主候选。

## 准备收尾（2026-10-25）

双组驱动a941206已普通push核实。执行`customer_workflow_comparison_live freeze`生成[新执行manifest](../../evals/customer-workflow-comparison-v2/execution-manifest.json)，绑定142文件及数据/模型参数；随后`check --output reports/customer-workflow-comparison-v2/frozen-preflight.json`通过，manifest_checked=true。命令和正式运行/源审步骤见[使用说明](how-to-run.md)。未发起正式收费对照，400仍是建议上限。

[最终保留审计](final-preparation-audit.json)核实原public11表与中性源步骤前相同、0自有/测试schema遗留、四历史脏文件字节一致、旧正式11报告及188历史报告hash一致、旧Agent/RAG manifest不变、ledger3053/无lock。原PG容器/原卷保持且55433监听；5174/8180–8183无监听，本轮未启停Java/UI；这里只重启过一次当时已退出的原PG。一次Docker inspect模板对bind mount取Name失败，随后用JSON结构检查卷通过，没有修改挂载。未改简历，RAG/Agent新业务指标仍为空。

当前交付为可执行评测设施及已知批量合同修复，不是新效果结论。剩余工作是用户安排后执行一次新完整配对、逐轮源审、汇总实际优劣及展示案例；不再以离线通过数量替代业务验收，也不自动追加重复或改判据追分。
