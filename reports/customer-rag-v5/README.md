# 客服RAG资料、设计与速度：统一实测

2026-10-21。用户明确关注数据资料、合适架构、合理速度。本批完成候选知识库、固定比较、真实GPU精排、实际PG只读阶段及并发机制复测；未发布新商家政策、未替换线上默认检索，也未新增付费生成模型。

## 1. 资料交付与适配

- [知识库](../../evals/customer-rag-v5/knowledge.json)：16个独立短单元，6条原受控政策逐字保留，加10篇依据当前实现整理的流程知识（订单选择、人工咨询、共享、私聊、接续、进度、重试、退款入口、事实来源、纠正）。不增加新退款资格、承诺时效、保修或运费政策。
- [来源清单](../../evals/customer-rag-v5/references.json)：本地文件/原文hash、外部四份固定政策及既有成熟系统源码目录；本次核查京东官方总则、Haystack检索组件、Sentence Transformers精排说明。外部文档用于组织/工程参考和旧长文档回归，不改成本店政策。
- [问题集](../../evals/customer-rag-v5/queries.json)：60条Codex合成问题、30编号家族，40开发/20冻结验收。开发32可答、4需实时工具、4未提供；验收16/2/2。实时订单/物流/退款不写进静态知识。三家政策正文相同，模板只计16独立单元，非48份独立样本；引用映射到本店文件/hash。
- [数据审查](dataset-audit.json)：同一作者构造/标注、非真实客户/独立盲测。虽然家族编号不跨组，复核发现验收Q28与开发resolved家族都问“解决后继续补充”，语义仍重叠；不能把编号隔离说成严格语义隔离。保留所有冻结分数，并附排除这2题的14可答题补充统计：RRF前三11/14、并集CE12/14，前五均13/14。后续新业务验证应另换该家族，不在本轮看结果后改Gold或补题刷分。

因此，这是一套更贴近项目的**小规模开发/冻结工程验收语料**，不宣称已经具备独立泛化证据。旧47外部题/商城9题仍是回归，不重命名为新测试集。当前16条规模很小，直接读取全库是必须保留的可行基线。

## 2. 固定架构比较

[协议](../../docs/customer-rag-data-design-speed.md)和[主manifest](../../evals/customer-rag-v5/manifest.json)先冻结。比较BM25、dense、三路RRF、RRF后读全局关联金额规则、候选并集GPU CE、全库GPU CE、直接全读。各路5、RRF60、最终3/5，原单Query，不额外改写/调用聊天模型。六条规则全局关联金额条款在测量前固定，不根据题号/Gold补证据。

开发阶段40×7=280次完整请求，保存[dev.json](dev.json)及按预先规则选定的`union-ce`，文件落盘后再执行验收20×7=140次，保存[acceptance.json](acceptance.json)并绑定开发报告hash。每组每题都独立重新编码/排序/forward，没有用预先分数冒充运行耗时。非可答题只存检索输出，不把命中材料当作已正确拒答/调用工具。

| 方法 | 开发前三完整依据 | 开发前五完整依据 | 验收前三完整依据 | 验收前五完整依据 |
| --- | --- | --- | --- | --- |
| 正文BM25 | 24/32 | 28/32 | 14/16 | 15/16 |
| 正文dense | 27/32 | 30/32 | 11/16 | 13/16 |
| 三路RRF | 27/32 | 31/32 | 13/16 | 15/16 |
| RRF＋全局金额关联 | 27/32 | 31/32 | 13/16 | 15/16 |
| 候选并集GPU CE | **31/32** | **32/32** | 14/16 | 15/16 |
| 全库GPU CE | 31/32 | 31/32 | 14/16 | 14/16 |
| 直接读取本店全部16单元 | 不作TopK比较 | 全包32/32 | 不作TopK比较 | 全包16/16 |

RRF关联策略的前3/5原排名指标不因追加金额规则改变；实际证据包覆盖也未修复Q16-2，说明不能只靠通用金额关联补齐所有缺失。全读满覆盖是来源材料性质，不等于最终答案正确。没有新增Agent生成回答，不能用此表决定最终业务解决率。

### 保留的反例

- CE在开发前三改善4题、无退化，按预设规则胜出；验收前三改善Q24-2（共享＋人工）和Q27-1（退款UNKNOWN），但Q22-1退化：物流查不到不能按未发货退款，正确未发货规则由RRF第1变为并集CE第4、全库CE第6。净增1题不代表稳定优于RRF。
- Q24-1“只想人工咨询、不退款，并想先看提交材料”：所有最终前5检索策略都漏K-SHARE；并集池缺该锚点，全库CE也仅把共享规则排第7。下一步该查流程章节关系/表达和Query保真，不能仅提高GPU精排模型复杂度。
- 全库CE反而两题前5不齐，比并集CE/RRF更差；全量候选更多不保证最终前5更完整。模型窗口非本批瓶颈，960对预检最大115tokens，无静默截断。

## 3. 本机热态速度：完整Query到证据包

[performance.json](performance.json)和逐请求记录绑定同一manifest。文件内存路径包括Query编码（需要时）、候选扫描/词法、融合/精排、完整短知识组装及本地token计数；不含HTTP、PG或LLM答案生成。CE含本地stdio与CUDA同步；原文均完整返回，不用精排分数过滤安全条件。

| 方法 | 开发P50 / P95 | 验收P50 / P95 | 验收来源包token中位 |
| --- | --- | --- | --- |
| BM25 | 4.26 / 43.76ms | 4.59 / 6.50ms | 516 |
| dense | 15.67 / 114.77ms | 14.36 / 44.92ms | 510 |
| RRF | 16.71 / 152.48ms | **16.91 / 22.69ms** | 526.5 |
| RRF关联 | 18.27 / 151.34ms | 16.19 / 21.91ms | 579.5 |
| 并集GPU CE | 55.14 / 302.08ms | **47.49 / 64.04ms** | 508 |
| 全库GPU CE | 59.95 / 281.14ms | 58.69 / 62.16ms | 500.5 |
| 全部读取 | 3.37 / 29.11ms | **3.19 / 4.16ms** | **1401** |

开发/验收时延不同，不能只选验收较快的一组作为稳定SLA。这些是一次顺序固定测量、小样本P95；基线没有“多传入约900tokens后LLM生成成本”的计量，不能据文件检索3ms就宣称全读端到端最佳。当前数据量支持先保留简单路线，不支持为了“技术含量”硬上复杂检索。

环境：主Python3.12.13/torch2.14.0+cpu/4线程，原固定BGE-small-zh；GPU worker Python3.11.15/torch2.11.0+cu128/transformers5.14.1、RTX5060 Laptop、cuda:0、FP32/TF32关闭，原BGE-reranker-base revision。不修改主环境、锁、外部CUDA环境或驱动；峰值allocated约1.07GiB/reserved1.13GiB。没有受控CPU/GPU同版本对比，不称加速倍数。

### 冷启动单独计量

文件实验首条Query编码29.05秒，其中模型导入/首次加载28.98秒，编码73ms；离线16正文编码330.95ms（模型已热），tokenizer加载279.94ms。GPU子进程启动39.38秒，子进程内导入/加载37.66秒；与旧批15秒不同，保留实际波动。不把离线建库算作每次检索，不隐藏首次加载。

应用当前已有权重复用，但仍惰性加载；**首问慢尚未因这次实验被修好**。启动预热/就绪检查是明确的下一接线方向，而不是把冷耗时从报告里删除。

## 4. 实际PG检索路径

临时启动保留PG，仅执行实际生产`retrieve_policy`三路/RRF、原固定generation/CPU4线程；9条旧商城Query×3轮，共27次。没有向文件知识库迁移PG，也没有启动Agent/Java业务worker。[pg-profile.json](pg-profile.json)保存真实阶段：

- 首次 **7986.77ms**，其中dense首次模型加载7383.74ms、首次正文BM25含jieba初始化约519.68ms。
- 后26次热态 **P50 34.73ms / P95 36.51ms**，包含scope、父规则/子块读取、编码、三路排名与融合；不含HTTP、回答生成或新候选知识包分词。
- 三轮排名一致；原P02主丢失规则遗漏仍复现，不能把热检索快当成回答效果已解决。
- 强制只读连接，public11表全行数/hash前后一致。测完已顺序停止PG，保留卷。数据库见证只有行数/hash，无原文快照。

文件与PG不是相同语料/接口，因此不能据17ms与35ms差额把“PG网络耗时”估算为18ms。

## 5. 并发瓶颈与复测

主实验RRF 40请求全部立即提交：1线程约52.01req/s、执行P95 21.81ms；4线程降为8.44req/s、执行P95 648.45ms，未达到预设并发热态参考目标，不能报通过。embedding锁等待中位约361.6ms。此时GPU worker已空闲但仍在进程中；本批没有足够证据把退化归因于GPU或某个运行库。

随后单独冻结[线程归属探针](../../evals/customer-rag-v5/concurrency-manifest.json)，比较共享锁下多线程调用与固定一个编码owner线程；同一个CPU模型/4计算线程/相同40问题，无CE、无缓存。首次探针Lint有一条长行，在保留结果后仅改行换行与新manifest路径，另[冻结v2](../../evals/customer-rag-v5/concurrency-manifest-v2.json)复测；两次结果都保留，不覆盖首轮退化。

| 独立复测 | 模式 | 并发 | 吞吐req/s | 执行P95 |
| --- | --- | --- | --- | --- |
| [第一次](concurrency-probe.json) | 直接共享锁 | 1 | 53.63 | 21.86ms |
| 第一次 | 直接共享锁 | 4 | 52.09 | 118.59ms |
| 第一次 | 固定owner | 1 | 55.22 | 21.91ms |
| 第一次 | 固定owner | 4 | 60.81 | 70.27ms |
| [第二次](concurrency-probe-v2.json) | 直接共享锁 | 1 | 50.99 | 22.74ms |
| 第二次 | 直接共享锁 | 4 | 40.62 | 121.06ms |
| 第二次 | 固定owner | 1 | 43.17 | 40.03ms |
| 第二次 | 固定owner | 4 | 54.02 | 82.67ms |

4并发下owner更稳一些，但1并发也有波动；首轮8.44req/s的严重幅度未在独立探针重现。不能宣称已经修复生产或得到固定倍数收益。所有探针输出来源包hash一致，固定owner没有复用Query结果来制造吞吐。

一次性提交40请求会产生调度队列：第二次4并发端到端批内等待P95为共享锁918.91ms、owner705.21ms，显著大于执行P95。报告同时保留执行与从提交起延迟，不把排队删掉；这不是线上HTTP压测或商业容量证明。后续应在实际工具调用方式下再决定是否接固定owner/批处理。

## 6. 采用结论与剩余边界

[架构与采用决定](../../docs/customer-rag-architecture-v1.md)明确：保留商家/版本过滤、Agent按需单Query、三路RRF与完整来源引用；极小语料必须保留全读基线。Cross-Encoder有开发收益，但验收净收益小且有退化，暂不设生产默认。长文档继续采用结构读回/去重引用的分层思路，不把外部整篇读回冒充商城召回提升。

本批同时交付资料、设计与速度证据；**不声称客服RAG已最终验收**。下一实际功能应是让流程知识按明确来源接入客服，并处理小知识库是否直接携带/何时调用检索及启动预热；新独立场景复测再判断CE。没有必要继续增加模型/算法网格来追这60题满分。

## 7. 命令与工程验证

```powershell
agent/.venv/Scripts/python.exe scripts/customer_rag_benchmark.py --freeze
agent/.venv/Scripts/python.exe scripts/customer_rag_benchmark.py --output reports/customer-rag-v5
docker start resolveflow-review-demo-postgres-1
agent/.venv/Scripts/python.exe scripts/customer_rag_pg_profile.py --output reports/customer-rag-v5/pg-profile.json
docker stop resolveflow-review-demo-postgres-1
# 新机制探针在观察首轮结果后独立冻结；当前源码对应v2，v1仅历史
agent/.venv/Scripts/python.exe scripts/customer_rag_concurrency_probe.py --freeze
agent/.venv/Scripts/python.exe scripts/customer_rag_concurrency_probe.py --output reports/customer-rag-v5/concurrency-probe-v2.json
```

以上输出/manifest拒绝覆盖，已存在时不重跑原路径。原探针源码压缩在[源码存档](concurrency-probe-v1-source.py.gz)，解压hash与v1 manifest完全一致；不让格式修正覆盖历史测量证据。

- 准备145a1f9已正常推送确认。新增语料模块缺失红测后6测试通过；结合原组装/精排/融合27通过，正式冻结前修正import、行宽、lambda。追加owner单线程/12并发调用不缓存测试通过。
- 最终agent目录、`PYTHONPATH=仓库根`下运行新知识/owner/原证据/精排/完整父级/子块/短引用/客服检索/Query/Agent/sources共**127通过、0失败/跳过**，4源码及2新测试Ruff通过；非全仓/Java/浏览器/LLM答案验收。一次读取不存在的app路径随后定位api/app.py，只读，未修改生产生命周期。
- 主manifest/最终探针manifest、原模型与来源hash收口核验。旧四历史脏文件保持，无生成模型API/新权重下载/生产写入；PG卷保留，GPU/CPU实验子进程已退、10端口闭，见[收口](completion.json)。结果/源码/文档精确提交、普通push确认后收口，SHA见本轮回复。
