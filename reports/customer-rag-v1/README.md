# 客服RAG修正第一批（2026-10-20）

范围：保存真实失败Query并作本地检索归因、共享embedding生命周期、分阶段计时。沿用原政策/READY generation/BGE/锁；没有新增生成模型调用，也不把人工参考Query当Agent改进结果。

## 1. 修改前诊断

输入：[冻结标注](../../evals/customer-rag-v1/queries.json)绑定[原始执行证据](../customer-agent-live-v1/runtime-results.json)的SHA256。3条实际模型Query各对照1条人工参考Query；另加6条合成口语探针覆盖原6类条款，两店各6条合成政策，不是正式盲测或大语料结论。

执行：仅启动原PG容器，`agent/.venv/Scripts/python.exe scripts/customer_rag_diagnostic.py --mode per-query --output reports/customer-rag-v1/before.json`。真实本地BGE、生产PolicyIndex、固定generation；24次只读搜索（12 dense+12 BM25），服务/worker未启。数据库连接强制`default_transaction_read_only=on`，public所有表前后行数/hash相等，完整记录见[before.json](before.json)。

| 分组 | dense必要条款Top3 | BM25必要条款Top3 |
| --- | --- | --- |
| 保存的模型Query | 2/3 | 2/3 |
| 人工参考Query（同3问题） | 3/3 | 3/3 |
| 合成口语探针 | 5/6 | 3/6 |

L08原Query的LOST条款两路都排第4，复现原失败；参考Query保留可信物流状态`LOST`并聚焦退款条件，两路都升第1。合成丢件口语P02的LOST在dense第5、BM25不在前5，说明当前术语表示/排序同样有问题，不能只归因于Agent问法。人工参考使用已知事实，有人工归因偏差，尚未证明模型能稳定生成它。

原先每Query新实例：第一次dense耗时9723ms（含进程首次import/加载等），随后11次69–99ms。不能把此前约59秒工具间隔全部归为模型加载，也不能把9.7秒作为每次请求开销。共享修复后的冷/热与各阶段需另测。

首次Ruff检查发现行宽及git可执行路径规则，格式化并改用解析后的路径；Git差异检查发现Windows写入CRLF，统一LF并在before记录纯序列化变更前hash，实测数值保留。

## 2. 共享embedding生命周期

- `SupportEmbeddings`由FastAPI lifespan拥有，默认HTTP咨询Runtime获得同一资源；只共享惰性权重对象，不共享HTTP凭据/消息/generation/预算。直接构造Runtime也可注入资源。
- BGE wrapper对首次加载及编码加同一可重入锁，加载失败下次仍可重试，过长查询仍拒绝截断；`embed_profiled`返回本次独立计时，记录等待/加载/编码。没有启动预热或额外模型服务。
- 退出释放资源引用；改配置路径替换单槽缓存，不累积多个模型。新资源/检索实现hash进入Support manifest，未完旧run仍拒绝换manifest，已完成结果仍可复用。

验证：新增并发加载/推理串行、失败重试/窗口、空输入惰性、应用隔离/关闭、API两次派发共享权重资源且Runtime分开的5项；先运行为2失败/2通过（缺新接口/模块），实施后连同原咨询API/Agent/来源、真实PG隔离Schema的SupportStore/PolicyIndex/完整性共64通过、0跳过。命令：`RESOLVEFLOW_AGENT_DB=postgresql://agent:agent@127.0.0.1:55433/agent_db`加`python -m pytest agent/tests/unit/test_support_embeddings.py agent/tests/unit/test_support_api.py agent/tests/unit/test_support_agent.py agent/tests/unit/test_support_sources.py agent/tests/integration/test_support_store.py agent/tests/integration/test_policy_index.py agent/tests/integration/test_rag_index_integrity.py -q`。未操作public业务行；保留1条既有Starlette弃用警告。

新/改源码及测试Ruff通过（从agent目录加载测试忽略规则；根目录首查曾误报既有测试SECRET规则）；4个源码严格mypy通过。未对既有app整文件宣称严格类型/格式通过，撤回工具带来的无关格式改动，仅保留3行接线。基线244d3e9已普通推送并核实远端。

## 3. 阶段计时与实际复测

`PolicyIndex.search(timings=...)`为可选旁路计时，覆盖固定版本/范围检查、父条款读取、子段读取及完整性验证、embedding总耗时（内部等待/加载/编码）、排名及结果组装。whole-rule与token-children两种布局均支持。`BoundSources`日志关联run_id与Query hash，不写Query原文/凭据，不把耗时塞进给模型的Observation、引用或持久工具响应。新增index/child实现hash进入Support manifest。

真实本地BGE分别在两个新Python进程执行：

```powershell
agent/.venv/Scripts/python.exe scripts/customer_rag_diagnostic.py --mode shared --output reports/customer-rag-v1/shared.json
agent/.venv/Scripts/python.exe scripts/customer_rag_diagnostic.py --mode per-query --output reports/customer-rag-v1/per-query-profiled.json
```

两次各24搜索；shared通过生产`SupportEmbeddings.get`取同一资源，per-query同代码/同计时但每Query新建wrapper。结果：[共享](shared.json)、[逐次新建对照](per-query-profiled.json)、[汇总及核验](comparison.json)。连同最初before共72次只读搜索，36dense/36BM25，无新增生成模型调用。新报告保存实际实现文件hash，测量时尚未提交的实现不能仅用HEAD标识。

| dense本地测量 | 每Query新建（带阶段计时） | 应用共享 |
| --- | --- | --- |
| 第一次总耗时 | 7512ms | 9964ms |
| 后续11次中位耗时 | 87.15ms | 25.66ms |
| 后续11次范围 | 64.71–230.40ms | 17.94–37.73ms |
| 权重加载次数/12Query | 12 | 1 |
| 后续模型加载中位耗时 | 55.76ms | 0ms |
| 后续Query编码中位耗时 | 20.38ms | 13.62ms |

共享首检索9809.68ms耗在首次import及本地模型构造，124.52ms编码；因此首次延迟尚未解决。本次预热后总耗时下降约71%，仅是这两个顺序执行进程、11次小语料查询的观测，不是压测/稳定性能承诺。最初before的对应中位78.76ms也保留，不用它替换带计时对照。父/子数据读取及校验在共享后各约2.90/4.07ms中位，当前证据不支持先上ANN或数据库扩容；这些阶段含Python校验和连接往返，不能称为纯SQL耗时。各阶段中位数不应直接加成总耗时中位数。

三份报告24个排名列表逐项完全一致；原Query依然2/3、合成探针5/6，说明共享/计时没有修复召回。所有11张public表的全行见证在每次执行前后以及三轮之间一致。READY generation/原政策/Gold未修改。

验收：阶段测试首轮3失败/6通过（两处接口缺失，另有新子段测试夹具误用start_offset而非现有start/end/text_sha256，随后修正夹具保留完整性断言）。实施后whole/children两个真实PG测试验证带计时与不带计时完整命中相同、复用计时字典无串数据、BM25无embedding字段；来源测试验证日志和模型Observation分离。最终上述64项加2布局项=66通过、0失败/跳过；5个改动源码严格mypy及相关源码/测试Ruff通过，1条既有Starlette弃用警告。未跑全仓/Java/前端（本次未改这些模块）。共享实现11d820e已正常推送并核实。

收尾：仅启动的原PG容器已stop，卷保留；10个应用/依赖端口全部关闭，见comparison。历史四个脏文件的差异保持，未夹带。第一批完成，下一批优先做基于事实与意图的Query生成及候选召回对照，再用新真实Agent回答验证收益；首次冷启动预热方案需单独评估。

## 尚未完成

- 自动Query生成的事实补全/主题聚焦与对照。
- 分字段、候选融合/重排的独立比较；没有部署BM25 fallback或把TopK增大当作修复。
- 外部原始政策语料验证、独立标注、完整Agent真实复测。
- 前轮物流故障读取语义、订单状态/物流状态混淆仍待处理。
