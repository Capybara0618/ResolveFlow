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

## 下一小步

接客服三路候选融合、保持原Query/动态工具选择，改善常驻Query生成指引；测试实际工具接线、引用和恢复，再验证真实本地检索。外部检索不部署进本店索引；真实模型Query/回答质量与完整业务复测本步尚未运行。
