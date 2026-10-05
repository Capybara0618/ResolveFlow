# RAG 第四批：索引完整性与查询诊断

2026-10-05，按[规格](../../docs/rag-optimization-batch4.md)执行。生产保持原正文dense，BM25仅为离线比较，不增加混合召回/重排/LLM改写。原v1/v2输入、政策、Gold、业务数据、资金审批、唯一AgentScope循环和依赖锁均保留。

## 已实现

- READY选择与实际读取绑定同一generation，避免同manifest多代块混读；相同时间有稳定ID排序。所有绑定bundle必须属于当前商家，不能用一个正确bundle掩盖另一个错误商家。
- 查询encoder的model/revision/dimension核对选中generation；build/query/存储向量检查数量/维度、NaN/Infinity/零向量，缺条款不当作无匹配政策。已通过SDK路径验证模型版本错配只调用一次模型并安全交接，不产成功Observation。
- [诊断脚本](../../scripts/evaluation/rag_experiments.py)同语料比较正文/标题正文的dense与BM25，记录前1/2/5覆盖及全部依据、完整依据倒数排名、返回字数、候选/分数和来源。目录只使用隔离eval_* schema，缺运行条件明确失败；已有输出不覆盖。
- [24条口语问题](../../evals/rag-challenge-v1/README.md)在排名前固定，Gold另存并受hash保护，但仍是同作者合成、未独立审查、非盲测。另提取三份已有live报告的8条模型查询，记录原案例/轮次/top_k/源hash；未标注逐查询Gold，永不套终局Gold计准确率。

## 检索实验

最终[368条检索记录](comparison-verified.json)：60原查询＋24诊断＋8已有live-query，四个表示/路径组合。相同本地BGE固定revision、PG过滤、政策/引用原文；新增付费调用0。原问题的正文baseline复现历史dense52/54、BM2549/54。

| 数据/路径 | 原正文前2条找齐 | 标题正文前2条找齐 | 原正文前5条找齐 | 标题正文前5条找齐 |
|---|---:|---:|---:|---:|
| dense/dev | 29/30 | 27/30 | 30/30 | 30/30 |
| dense/已查看test | 19/24 | 20/24 | 22/24 | 23/24 |
| dense/合成口语诊断 | 21/24 | 21/24 | 23/24 | 24/24 |
| BM25/合成口语诊断 | 12/24 | 11/24 | 17/24 | 17/24 |

预先规定只按dev门槛选择：前2条/前5条完整依据不退化，完整依据倒数排名严格改善。标题正文dev倒数排名0.9278→0.8833，前2条29→27，门槛失败，**未部署**。不能因已看过test成绩更好就选它，更不能隐藏退化。新诊断仍同作者，结果支持继续调查“口语对关键词匹配的影响”，不能证明真实BM25一定不好。

当前正文dense在诊断题D02-unknown遗漏“履约信息不足”依据：付款页面打不开、扣款也不清楚，却先返回退款范围/未发货等条款。该失败保留，不改Gold补分。原无适用政策6题均返回候选，分开计数；相关候选不等于退款适用性，不以强制空结果提高分数。全部368记录错主体/版本0。

诊断正文dense平均前2条正文/标题合计214.29字符，前5条约五条规则；这是候选文本量，非实际provider token/整个上下文。Baseline计时包括PG/查询embedding，候选使用预计算向量且仅计排序，**不进行速度提升比较**。

## 工程验证与失败

最终51模块680 passed/0 skipped（1依赖弃用警告），追加版本/manifest/主体泄漏评分[10项通过](diagnostics-verified.txt)（新增4项，合计684不同项）；集中结果见[tests-final.txt](tests-final.txt)、[JUnit](tests-final.xml)，精确命令见[commands.json](commands.json)。Harness[28/28](harness.json)，当前source十三条[严格回放13/13](replay.json)；独立新[rag-v8](../../evals/replay/rag-v8/manifest.json)，correction-v7及旧包不覆盖。数据[冻结校验](validate.json)保留，Ruff和diff通过；[mypy](mypy.txt)仍16既有错误/9文件/72源码，不能称全项目类型门禁通过。

先失败检查：[12 failed / 1 passed](integrity-before.txt)，维度错误旧路径已有拒绝，其余新失败复现。补实现后[5 failed / 47 passed](integrity-after.txt)：未embedding错误被新检查遮盖，恢复原明确原因；旧政策读取测试无物流来源却声称承运商丢失，触发现有Harness事实拒绝，改为通用人工复核说明，不改业务事实。再跑[1 failed / 58 passed](integrity-fixed.txt)：旧测试要求prompt包含hash，与既有短引用协议不符，改为断言实际可见P#别名能精确展开所有原引用字段，保留完整性保证；[7项专项通过](search-fixed.txt)。首次集中[679 passed / 1 failed](tests.txt)，新增SDK测试错误地修改冻结dataclass字段，改用新encoder副本后重跑最终集中。

收尾生成manifest的第一条诊断命令误用pack的harness_manifest字段（实际名manifest），明确报KeyError后按实际结构生成；未覆写旧profile/放宽strict。所有候选实验报告保留，comparison-verified补显式版本/manifest计分及实际组件源码hash，排名不变；纯指标补充没有改变候选排名或Gold。

## 未证明与未运行

政策/固定题/Gold原由同一脚本编写；分文件和增加合成口语问题不产生独立数据。每bundle仅9条、三店8条通用正文高度重复，top5很容易偏高。旧test已参与调试，不称盲测；独立用户问法/专家Gold/新独立冻结测试仍待补充。8条live-query也是合成案例上的真实模型输出，不是用户日志，更不代表当前最终Agent运行准确率。

未运行新的DeepSeek/真实Agent前后建议质量对照、Java整链、网页验收、业务服务重启/部署、生产索引重建或历史队列消费。当前代码不改变索引表示或引用hash，健康旧索引无需因本批重建；metadata不一致/缺块必须明确修复，禁止静默降级。新run下次正常服务启动加载当前代码；旧run不静默换manifest。

生产/public与用量只读核对记录于[read-only-state.json](read-only-state.json)；原四历史脏文件、草图及日志未夹带，commit与正常push远端确认见本轮收口。
