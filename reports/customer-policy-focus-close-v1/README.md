# 政策追问质量收口（2026-10-23）

按用户“完成收口政策追问这个质量缺口”实施。原失败记录在[单场景真实确认](../customer-policy-focus-live-v1/README.md)，不覆盖原输出或Gold。

## 第一步：有界完整政策上下文

现有每店仅六条短政策，原Query前三漏掉两条关键规则。客服`search_policy`现先检查原绑定政策集合是否足够小：不超过8条且包含来源字段的序列化UTF-8内容不超过8192字节时返回全部原文；超限仍走原三路/可选双分支检索。共同复用原商家、manifest、READY generation及行数完整性校验，不使用规则ID或问题关键词挑政策，不改旧索引。

`top_k`是排序路径的结果数，小集合完整返回允许多于它；工具说明/schema显式写明，观察标注`retrieval_context.mode=COMPLETE_SMALL_SET/count`，运行manifest记录版本/上限。这个模式不做dense/BM25或embedding降级冒充，完整上下文的path明确为complete；检索模式保持原错误语义。

[offline.json](offline.json)使用原真实Query及原generation，只读实际PG、不加载embedding，六条均完整返回，单次20.96ms，public全表hash保持、新LLM/HTTP0。这保证这个小集合的条款覆盖，不证明选取相关条款/回答质量，也不当作大语料RAG效果或性能百分位。

实际验证：

- `RESOLVEFLOW_AGENT_DB=postgresql://agent:agent@127.0.0.1:55433/agent_db`；在agent目录执行pytest，关键新增测试先红：初次测试参数ID过长造成2个setup错误，缩短ID后另有测试语料超4000字，改为合法长规则；缺能力的红测保留。实现首轮canonical不接受float score，改用无排序整数零后通过。
- `pytest tests/unit/test_support_sources.py tests/unit/test_support_retrieval.py tests/integration/test_policy_index.py tests/integration/test_support_retrieval_index.py tests/integration/test_support_small_policy.py tests/integration/test_support_staged_api.py tests/integration/test_support_stream_runtime.py tests/integration/test_policy_focus_live_driver.py -q --tb=short`：**53通过、0跳过（28.44秒）**，包含真实PG/SDK、原排序路径、完整供给、大小限制、绑定generation与跨商家拒绝、流式及隔离driver。原第三方Starlette弃用警告1项。
- 三个主要改动源码strict mypy通过；新增service manifest及最终格式另做Ruff。原四脏文件/旧清单/probe与原真实结果SHA保持；未新增真实模型请求，账仍2025。

下一步同一授权内处理上下文中的历史/当前事实区分，再冻结有限真实确认，判断模型是否能从完整集合选择相关条款。当前不能凭完整供给就称最终回答已修复。

## 第二步：历史来源与条件解释范围

历史助手、客户和商家原文分别标记`HISTORICAL_ASSISTANT_OUTPUT / CUSTOMER_STATEMENT / MERCHANT_STATEMENT`，覆盖最近消息、历史预览及精确回读，不改持久原文，不把历史消息放入fact_view。已接受焦点若需要POLICY且不需要ORDER/SHIPMENT，stage显式给出`policy_scope=CONDITIONS`；模型应按相关主题解释条件，不能借旧助手发言认定本单当前状态。需要判断本单时仍可自主追加事实需要并读取，不固定所有政策问题先查物流。

- 两个新增关键断言先红（2失败/20通过），实现后定向42通过。首次扩大`-k support`选中353通过、4跳过、1失败；失败为较长目录说明令旧Mock保守包溢出，去掉目录重复说明、保留schema/观察中的完整模式说明后，**精确客服单元+实际SDK/PG/流式/完整供给/旧确认driver共328通过、0跳过（23.47秒）**。不增加预算或删除原断言。首strict发现authority的Optional键类型，明确转换后strict三源码通过；Ruff通过。
- 新三场景驱动`scripts/close_policy_focus_live_v1.py`复用既有真实流式/发送前记账/独立schema驱动，整组硬上限12次模型、3个独立追问、每题一次、失败不重跑，有限结构修复仍计费计数。两项驱动单元通过（2.25秒），验证旧历史/事实/pin不改、整组上限在发送前生效、失败清理driver配置、不可再次执行；Ruff/py_compile通过。
- `prepare`已冻结[三场景计划](../../evals/customer-policy-focus-close-v1/plan.json)、[逐场景输入/源码SHA](live/manifest.json)：原追问、切换质量问题、假设未来承运商确认丢失。沿用原合成历史/业务快照和真实本地政策，新run、原public保持；不测浏览器或简历，不强制工具路径/分支，新增真实模型仍0、usage2025。准备提交普通push核实后，仅执行本组一次并审查全部输出。

## 三场景真实结果及剩余范围问题

生产793c76d按冻结计划执行一次，三run全部运行成功，**11次真实请求，账2025→2036，准确Provider输入43779/输出1554 tokens**，全部输入/决策/流式/工具/来源见[live/results.json](live/results.json)及逐题原文件，[来源审核](live/review.json)结论为PARTIAL，不覆盖前一次失败。

| 场景 | 模型次数 / Agent耗时 | 实际内容 |
| --- | --- | --- |
| 原追问 | 3 / 6859.01ms | 普通在途/确认丢失条款均取得，材料非强制、无无源当前断言；仍将未发货/签收/通用资金边界展开，范围偏宽 |
| 切换质量 | 3 / 5066.25ms | 正确转到质量核验和材料建议，没有假定货已到或继续回答物流；通用资金段仍偏冗余 |
| 假设未来丢失 | 5 / 7063.59ms | 保留假设，没有认定已丢失；理解多声明SHIPMENT，首次回答漏该来源而被原Harness拒绝，经一次修复读取冻结物流后发布，最终当前状态有本轮来源 |

每题工具均完整返回六条原政策，public前后hash保持/本次私有schema已导出删除。耗时非浏览器或百分位。没有失败重跑；假设题的一次结构修复完整保留并计费，不能称三题均只三调用。关键证据覆盖和历史当现状的缺口改善，但原追问的焦点仍概括成“一直未收到货政策”，所以不能据此宣称已全部收口。

## 第三步：显式承接范围

理解focus可给至多三个`context_refs`历史H编号，在请求中保留具体主题；调查阶段沿这些原话限定话题。编号由原历史投影提供，承接引用不授予事实权威，重复/未知编号在接受任何事项状态前拒绝。新主题不强制继承历史，原缺省协议保持。仅查询一般/未来政策不应因历史谈过物流而声明实时物流需要；回答以主题及必要前提、材料为主，不默认罗列全类别和通用资金/实现机制。

同时修复只读发现的排序路径观察标记：结果条数变化不能改变相同政策的来源身份，RANKED标记不再携带本次结果数；完整小集合count仍保持真实总数。这不改变上组三题完整模式结果。

- 新历史承接与来源身份断言先红2失败/22通过，修后定向33通过；Ruff首次长行已修。**客服单元+新驱动+实际SDK/PG/流式333通过0跳过（23.48秒）**，四源码strict/Ruff通过。不修改原评判/增加预算/削弱断言。
- 原三题输出冻结，下一次仅对原追问做新源码版本的[scope-v2确认](scope-v2/manifest.json)，新run、**最多4次请求**、不改变原问题/政策/Gold、不自动失败重跑。独立包装`scripts/confirm_policy_focus_scope_v2.py`经Ruff/py_compile，复用已验证的同一驱动/账/流式/临时库边界；prepare新增模型0。提交普通push核实后execute一次，按真实focus/context_refs与最终相关条款审查，不把新增元数据本身当效果。

## scope-v2失败与提示契约修正

773a9bd下的[原始确认](scope-v2/runtime-results.json)未发布答案：理解仍给POLICY+GUIDE且未输出context_refs，首次回答缺声明GUIDE而被原Harness拒绝；第4次请求选择读指南，第5次模型调用在发送前被4请求硬上限阻止，运行FAILED/ValueError。准确Provider **4请求、输入16592/输出720**，账2036→2040；Harness含第5次未发送请求的预留，不能当5次收费或实际token。public保持/自有schema已导出清理，不重跑这个run或覆盖失败。

复核发现理解JSON示例仍未展示context_refs，并默认LOGISTICS/SHIPMENT，与新增说明不一致。现改为无默认事实读取的完整字段示例，把材料条件与页面操作的区别放在前面，并明确承接原话如何形成具体问题；调查回答按承接主题给直接规则、必要变化和材料，不概览全部同词场景。没有改政策/Gold或原输出，也没有将某一政策ID写入路由。

新增示例契约关键红测1失败/15通过，修后客服相关全套**334通过0跳过（19.93秒）**、Ruff/strict通过；单场景包装增加显式output/请求上限并仍拒绝覆盖旧结果，三项驱动单元通过（1.97秒）。新源码[scope-v3输入/manifest](scope-v3/manifest.json)已prepare，仍仅原追问一次，明确至多6次真实请求，允许原循环的有限结构修复，不增加生产RunBudget。旧scope-v2封存；提交普通push核实后执行新版本一次，结果仍需源审，不预先称成功。
