# 真实Agent查询、政策返回与建议的来源审查

2026-10-06。**这批没有发现当前32次实际检索漏掉查询所需的范围内规则；更值得修的是补证责任、关键阻碍的说明以及纠错停止的解释。生产排序保持dense，不将公开网页的去重收益直接部署到现有规则上下文。**

按[审查规格](../../docs/agent-rag-source-review.md)，复用已完成真实模型请求，不再收费。原Gold/自动评分/模型评判/失败均保持；新[查询及建议标签](../../evals/agent-rag-source-v1/labels.json)由Codex依据原文与实际输入审查，已见旧结果，不是盲测或真实客户准确率。进度只维护tasks/todo.md顶部。

## 1. 查询究竟有没有执行

[审查机器结果](audit-v1.json)核对当前32例、165份实际请求、33个SEARCH_POLICY动作及Observation来源。

|口径|当前记录|解释|
|---|---:|---|
|模型提出政策检索|33|包含非法动作，不能作为实际检索分母|
|实际检索|32|每例一次，原top_k全部3|
|格式拒绝、未执行|1|A13B第3轮多余type；下一轮合法检索成功|
|下一模型请求中有完整政策正文|32/32|规则身份、版本、Java式hash、完整正文均核对|
|可完整回答政策主题的实际query|31|条件式政策回答与本案是否符合条件分开|
|这些query前2/实际前3全依据覆盖|30/31、31/31|A07A的丢失主条款排第3|
|部分可答query|1|A01B引入语料没有的七天无理由；只找到系统已有处理范围，不能说已回答七天政策|

部分可答的范围内规则在前2/前3都齐全，但缺失主题没有答案，故不能把32/32范围内证据覆盖写成32/32完整回答。基线33个检索动作均实际执行，只复核执行计数，没有把基线的33个query套用本次标签。

当前query由模型直接产生，没有额外一次LLM来改写；一般为短的“事实/诉求＋条件/核验”组合。三个query没有提已知退款占用，四个query触及尚未取得的事实；这些是上下文/事实适用风险，检索关键词不能当已确认事实。相关标记及具体来源绑定在labels.json，不是生产按题号匹配规则。

## 2. 生产与公开文档不是同一语料

32例使用calibrated-v3中的六个商家/历史版本bundle，每版9条合成规则；实际只钉住三店v2。生产Java业务的基础政策则每店6条。上批公开HTML有66子块/宽父章节，不能将它的分数或20.58%正文节省搬到本次。

本批核对所有165份保存请求：67份已有政策P2，其中完整正文与对应商家/版本规则相同，相同规则身份不重复。现有ReferenceCatalog和policy_table已做到短引用/完整正文去重；没有同一源规则重复发送的正文可再按上批方法删除。因此本次不修改生产上下文，不新增query改写LLM或融合默认路径。

另外，通过**PG只读、可重复读事务**重新读取一笔已结束的Java业务run，没有启动调查或创建新工单；完整请求快照留在忽略tmp。原记录是3次SAVED/live模型请求、2次工具读取，来源为已有部署验收的合成购买。离线[业务来源核查v2](business-source-v2.json)验证原query“未发货 取消订单 退款 条件”及最终所用引用。

它的实际前3排序为质量、未发货、签收争议；未发货条款排第2，完整条件/例外进入下一轮P2，最终建议REFUND并被原Java链路接受。这证明**排序仍有不适用候选噪声**，也证明排序第一不代表适用；一笔样本不足以支持切换算法。它不加入32例质量分母。旧政策文字里的“售后专员”仍是已发布历史版本用语，未因角色合并静默改hash。

## 3. 建议的主要缺口

31份有有效终局，1份未完成。原自动31/32逐字段复算相同，不修改原成绩。按Codex来源审查，完成者事实/政策支持各31 PASS；动作理由29 PASS/2 WARN，商家可读性24 PASS/7 WARN。这些维度按保存来源审查，不是新模型准确率，正确安全动作与说明欠缺分开记录。逐份见[32例说明](cases.md)。

|问题|具体来源|处理方向|
|---|---|---|
|补证责任主体错误|A04B订单NOT_FOUND，却REQUEST_INFO要求商家履约记录|系统/商家数据缺口交商家查；客户补证只问客户可提供的内容|
|补证不具体、遗漏占用|A07B REQUEST_INFO无questions且missing_evidence为空；summary漏RESERVED|先说明资金占用，再说明待核验事项及负责人；区分建议补证与真正发QUESTION回调|
|关键阻碍没有出现在摘要|A16B的finding有RESERVED，summary仅说无成功退款|摘要保留影响决定的阻碍，不只保留支持最终动作的一个理由|
|人工转交太泛|A01B/A02B/A08B/A12B真实ESCALATE仅通用reason_code|保留缺失/冲突的来源与商家下一步，避免增加一堆泛化小字|
|纠错后仍无有效建议|A15B两次PROPOSE引用结构不合法|给出准确字段关联反馈，维持有限修正；轨迹区分模型决定与Harness停止信号|

REQUEST_INFO的PROPOSE是给商家的补证建议，不等于ASK_CUSTOMER，也不会凭一个动作字符串自动发客户问题。当前worker仅ASK_CUSTOMER生成QUESTION回调，Java买家页面依WAITING_CUSTOMER及问题记录展示补证入口。因此不能以自动Gold允许REQUEST_INFO就声称客户补证链已经在这些案例中完成。

### 纠正原A15B解释

原rag-delivery README写“模型随后ESCALATE”。本次逐份原始provider请求核查发现：第5次模型PROPOSE的CONFLICT只有O1；第6次仍是PROPOSE，但finding引用O4、evidence_refs却仅O1/O2。两份保存响应经相同引用展开/校验复现拒绝。

轨迹中的ESCALATE来自sdk_runner在gate停止后向SDK返回的REFUSED停止信号，**不是供应商模型的一次有效人工转交**。结果completed=false、decision=null、ACTION_REFUSED保留；没有第7次收费请求。新[终止来源证据](termination-source.json)纠正解释，原报告与成绩不覆盖。这是解释层的修正，不是放宽Harness约束。

## 4. 已交付工程与验证

- scripts/agent_rag_source_review.py：冻结hash、实际执行对齐、完整政策/下一轮P2来源、独立query标签及旧工程评分复算。重复/歧义、漏记录或错误版本明确失败，不把非法请求计成召回失败。并未用关键词程序自动生成语义标签。
- scripts/agent_rag_business_review.py：读取私有保存快照，离线核查Java业务政策引用全部5个字段与原正文/下一轮P2，不访问实时API、也不发模型请求。零检索不能报成功。
- 新15个测试覆盖拒绝与执行分母、歧义/坏hash/版本/正文末尾、表格、空标签、归档失败Observation反序列化及业务来源/引用/零执行。集中相关128 passed/0 failed/errors/skipped，4.59s，见[JUnit](tests.xml)；Ruff按项目agent配置通过。
- 21冻结输入一致；当前审查及业务v2各复算一次，JSON完全相同。主审查与旧结构/Gold/生产源码无变化，三条实际业务模型响应保持SAVED/live。完整请求/凭据/数据库/原文缓存不提交。
- 首次新测试因模块不存在而收集失败，之后实现。Lint import/长行修复。首次审查将归档字符串枚举按Python对象加载被严格校验拒绝；改JSON加载后又遇归档model_dump输出的失败源null默认值。归档适配只在有error且版本/hash均缺失时省略二者，单边身份或无error仍拒绝；没有改生产wire校验。两失败发生在完成审查报告之前，manifest记录且旧标签/原数据不变。
- 业务初版v1验证后补负测发现空检索可误报成功、批准引用只核对规则ID；2 failed/6 passed保留为开发过程，补齐零执行拒绝及全字段引用核对，8项通过，再生成新v2报告。v1不可覆盖并保留，旧runner快照只在tmp；不得把v1当最终完整门禁。
- 未运行全仓、Java/浏览器/mypy或新付费整体Agent，未部署算法/重新索引/消费队列/审批退款。历史16类型诊断及8可见测试失败保留。本批128项不代表全项目门禁通过。
- 收口辅助检查首次误用标签字段category（实际为answerability）出现KeyError，修正辅助脚本后复核；无冻结输入或评分变化。核对终止证据描述的实际方法名为_GateAwareClient.decide，不改模型响应或拒绝原因。

实际命令：

```powershell
agent/.venv/Scripts/python.exe scripts/agent_rag_source_review.py --output reports/agent-rag-source-review/audit-v1.json
agent/.venv/Scripts/python.exe scripts/agent_rag_source_review.py --output tmp/agent-rag-source-v1/audit-repeat.json
agent/.venv/Scripts/python.exe scripts/agent_rag_business_review.py --snapshot tmp/agent-rag-source-v1/business-source-snapshot.json --policy fixtures/demo-foundation/policies/policy-foundation-m1001-2026.10.yaml --output reports/agent-rag-source-review/business-source-v2.json
agent/.venv/Scripts/python.exe scripts/agent_rag_business_review.py --snapshot tmp/agent-rag-source-v1/business-source-snapshot.json --policy fixtures/demo-foundation/policies/policy-foundation-m1001-2026.10.yaml --output tmp/agent-rag-source-v1/business-repeat.json
agent/.venv/Scripts/python.exe -m pytest -q agent/tests/unit/test_agent_rag_source_review.py agent/tests/unit/test_agent_rag_business_review.py agent/tests/unit/test_rag_probes.py agent/tests/unit/test_evaluation_scoring.py agent/tests/unit/test_semantic_review.py agent/tests/unit/test_short_references.py agent/tests/unit/test_correction_loop.py agent/tests/unit/test_context_quality.py agent/tests/unit/test_context_calibration.py agent/tests/unit/test_proposal_verifier.py --junitxml=reports/agent-rag-source-review/tests.xml
agent/.venv/Scripts/python.exe -m ruff check --config agent/pyproject.toml scripts/agent_rag_source_review.py scripts/agent_rag_business_review.py agent/tests/unit/test_agent_rag_source_review.py agent/tests/unit/test_agent_rag_business_review.py
```

业务快照通过本机PG55433、BEGIN后`SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY`，参数绑定原verification.json中的run_id，查询agent_model_call的call_id/state/request_body/response、agent_tool_call.observation及agent_run_model_budget.manifest。没有调用exercise、migrations、start、HTTP写入口或模型。输出JSON/hash只在tmp；核验完整步骤及原数据仍可在本机复现。复算用新文件名，缓存缺失明确失败。

## 5. 后续实施选择

**先改建议与Harness输出边界，再决定是否重做整体真实对照；当前不优先继续调RRF。**

1. 上下文/反馈通用地保留当前退款占用、未确认事实与已有回答；修正反馈点名不在evidence_refs中的finding来源，禁止为了满足数量随意补无关来源。摘要说明关键阻碍，但不追加一大段规则。
2. 明确补证责任和输出方式：客户能回答的才ASK_CUSTOMER；系统/商家核验缺口转人工。给商家的REQUEST_INFO建议须具体、不能声称已发客户问题。沿用现有回调/审批协议，不自动把旧建议改成执行。
3. 为轨迹展示区分provider动作与Harness/SDK停止信号，保留原原始记录、reason_code及有限修正，不把停止当成功建议。不扩大为通用Agent平台。
4. 先用不同状态/表述的同类变体验证，再在统一输入/模型配置下做一次整体对照。真实收费不默认自动开始。当前6/9条合成规则无法证明复杂长文档RAG质量，外部原文到商家适用条款的边界仍须明确，不能靠查询相似度赋予退款权限。

可迁移经验：**观察记录、实际模型输入、最终有效建议和SDK终止事件是四种不同证据；只看命中列表或轨迹里的一个动作名，很容易把根因归错。**
