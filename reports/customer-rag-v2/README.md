# 客服RAG第二批：Query与候选召回（2026-10-20）

沿用户授权，先冻结输入比较，再选择客服咨询接线；不更换框架/模型/依赖，不重建原政策generation。第一批见[基线](../customer-rag-v1/README.md)。

## 小步1：实际离线比较

Query仍由Agent现有决策生成，不新增LLM改写调用。新增`grounded_query`作为**离线候选**：从当前run已读SHIPMENT中限定当前line，选择最新无冲突版本的状态，给原Query添加明确来源字段。不从客户陈述、POLICY或ORDER提取物流事实；UNKNOWN保持UNKNOWN，读取失败不沿用旧成功，超长不截断。未接入生产Query替换。

检索候选：原正文dense、正文BM25、标题BM25、dense+正文RRF、dense+标题RRF、三路RRF。每路候选5，最终Top3另查Top5，RRF常数固定60/同权，词法只纳入正分数；不把不同路的原分数直接相加。标题单独检索，不重新embedding标题+正文；返回完整原文、条件/例外和原引用。融合按bundle+chunk去重，逐文档核对原文和版本，先通过现有商家/manifest/generation门禁。默认PolicyIndex仍为原dense/body行为。

运行：仅启动原PG，`agent/.venv/Scripts/python.exe scripts/customer_rag_candidates.py --output reports/customer-rag-v2/candidates.json`。输入复用[已冻结9场景](../../evals/customer-rag-v1/queries.json)及3条真实模型Query前的实际工具观察；6合成口语探针不虚构已确认事实。共54次搜索（18dense、36词法），108个Query×算法结果；不是108个独立问题，参考Query未混入自动Query分母。

| 原Query算法 | 真实模型Query必要条款Top3 | 合成口语必要条款Top3 | 新增漏召回 |
| --- | --- | --- | --- |
| dense | 2/3 | 5/6 | 基线 |
| dense+正文RRF | 2/3 | 3/6 | P03、P05 |
| dense+标题RRF | 3/3 | 5/6 | 无 |
| 三路RRF | 3/3 | 5/6 | 无 |

见[实际排名/时间/hash](candidates.json)。L08原Query的LOST由dense第4变为两种带标题融合第1。P02“快递确认弄丢了”的表达在这些候选下仍漏，不能称所有丢件问题已解决。词法零分过滤后单路BM25合成2/6，和第一批按零分也填满TopK的3/6不同，规则已明确，不能把它包装成同定义提升。

**拒绝强制状态拼接**：L08的fact-anchored dense改善，但L02拼DELIVERED反使SIGNED掉出Top3。3条总体仍2/3，却换了失败例；这正是逐例退化检查的作用。保留代码/结果供离线归因，不把它作为生产自动改写。

## 外部原始文档补充对照

沿用4份官方快照/3来源家族、66检索片段、29问题和既有Codex来源复核；不更新Gold/来源/向量。复用缓存Query向量，无新embedding或聊天API调用。`scripts/customer_rag_external.py --output reports/customer-rag-v2/external-final.json`检查原始输入hash/片段血缘/Query向量输入一致，仅本地排名，不读取业务库。[最终结果](external-final.json)中正式accuracy为null：这些是已看过来源和排名的Codex开发标注，不是独立人审或盲测。

| 算法 | 17个ANSWERABLE的Top3完整原子覆盖 | Top5覆盖 | 相对dense的Top5退化 |
| --- | --- | --- | --- |
| dense | 10/17 | 13/17 | 基线 |
| dense+正文RRF | 10/17 | 12/17 | S:JD03、S:MI01 |
| dense+标题RRF | 10/17 | 12/17 | S:MI01、S:IK05 |
| 三路RRF | 12/17 | 16/17 | S:JD03 |

1个PARTIAL另报，11个需澄清/无答案问题不计完整答案分母，不把召回当答案存在。度量要求完整来源块/表格行的充分依据覆盖，不扩父段；外部长文section_path也不同于商城短规则title。因此选择三路RRF是当前客服开发候选，不宣称对所有语料稳定更好或自动修复长文条件。S:JD03退化完整保留；没有扩TopK刷分或接外部文档为本店生效政策。

验证：新增Query/去重融合/真实PG标题读取8项及原PolicyIndex/两布局计时/索引完整性共44通过、0跳过；三个源码严格mypy通过。先红测2个模块缺失、标题接口缺失；首次标题夹具只有2条使BM25单次词IDF为0，改成3条明晰字段夹具，未改变生产BM25公式或删除断言。脚本初查行宽/闭包绑定规则失败已修正，外部静态修正重跑逐项一致；中间输出保留本地，不作为最终结果。源码/测试/两脚本Ruff通过。public全11表在本地搜索前后hash相同，没有新生成模型调用。

## 小步2：客服接线与实际工具验收

已接`BoundSources.search → retrieve_policy → PolicyIndex`，使用三路同权RRF；原Query原样传入三路，不用离线状态拼接。各路固定原generation，只有一次dense编码，每路最多5候选，最终仍遵守Agent指定1–5条；标题/正文词法仅正分数进入融合。任一路失败则本次搜索不可用，不悄悄用dense或BM25代替完整策略。计时日志区分dense/正文词法/标题词法/融合，模型Observation和引用不加入排名分数/计时字段。旧退款调查仍dense；没有重建政策或新增数据库迁移。

常驻指引增加当前意图/有效历史、否定/假设、客户陈述与可信事实、订单与物流状态分别理解、不新增补发等意图、缺主题时自主重查；不强制预读工具、拼状态或新增LLM调用。新prompt/code hash与`support-fields-rrf-v1`/候选数/RRF参数进入manifest，保留旧完成结果复用、未完成run不静默换逻辑。提示词接线通过不等于真实模型已稳定遵守。

实际工具：`agent/.venv/Scripts/python.exe scripts/customer_rag_runtime_check.py --output reports/customer-rag-v2/runtime-final.json`。直接调用生产`BoundSources.search`+真实BGE+只读PG，在旧固定generation上核验9条原Query，HTTP传输显式禁止，无新run领取/持久化或生成模型调用。9条的Top3都与离线选定三路排名一致，3条保存模型Query必要条款3/3，6条合成探针5/6，引用保持原店/manifest/正文hash，见[实际工具结果](runtime-final.json)。这不是模型重新生成Query或回答的完整回放。

该工具实测首次8143ms、随后8次中位35.00ms；范围仅当前短政策集，不是端到端或并发SLA。增加词法路径有额外开销，第一批共享dense中位26ms来自不同查询组合，不当作严格同组差额。首次加载仍慢；P02口语漏召回、外部S:JD03退化和最终回答适用性继续保留待查。

验证：新接线先红测2失败/3通过（缺新入口）；原来源测试因fixture没有真实PolicyHit.score而失败，补为完整PolicyHit并继续核对全部商家/generation/原Query及三路调用，不删除旧隔离断言。新增测试包含同一原Query/固定generation/最终top_k/旁路计时、dense失败不回退、后续路版本失效不返回部分结果。最终咨询/接口/embedding/查询/融合/真实PG持久恢复/索引及两布局计时共**77通过、0失败/跳过**，保留1条既有Starlette警告。4个改动源码严格mypy、相关源码/测试与脚本Ruff通过。未改Java/前端，未运行其构建或新真实模型测试。

实际最终命令（agent目录，`RESOLVEFLOW_AGENT_DB`为原本机55433）：

```powershell
.venv/Scripts/python.exe -m pytest tests/unit/test_support_retrieval.py tests/unit/test_support_query.py tests/unit/test_support_sources.py tests/unit/test_support_agent.py tests/unit/test_support_api.py tests/unit/test_support_embeddings.py tests/integration/test_support_store.py tests/integration/test_support_retrieval_index.py tests/integration/test_policy_search_profile.py tests/integration/test_policy_index.py tests/integration/test_rag_index_integrity.py -q
.venv/Scripts/python.exe -m mypy --strict src/resolveflow/support/engine.py src/resolveflow/support/retrieval.py src/resolveflow/support/service.py src/resolveflow/support/sources.py
```

收尾失误如实记录：首次77项通过后，在包含最终manifest参数的复跑尚未结束时提前stop了PG，产生9个ERROR进度并使迁移连接等待，**该次运行作废**。恢复PG后结束本轮被打断的pytest进程；唯一遗留`t_d280932b6d11458b`只有2个空表，核实文件修改时间在本轮runtime验收后，使用原drop_schema只清理该自有隔离schema，未触及public；随后完整重跑77通过。复跑结束后核验无`t_*` schema、public11表全行见证与第一批完全一致，再顺序stop PG。10端口全闭、卷保留，见[完成清单](completion.json)。开发脚本静态问题、无改动的中间输出均保留本地；只发布通过核验的final报告。

独立小步1b2d28a已正常push核实；本步接线/测试/报告精确提交并正常push后核实，SHA见回复。原四历史脏文件保持且不夹带，无新增生成模型用量。下一步需要新真实模型Query及有条件回答复测，不能直接将本批召回数字写成客服解决率或简历最终提升。
