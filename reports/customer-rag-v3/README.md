# 客服RAG第三批：候选并集与Cross-Encoder（2026-10-20）

用户批准固定Query比较当前RRF、候选并集精排与商城全规则精排；随后明确本机有GPU，要求使用GPU推理。生产策略/依赖锁/旧报告/Gold保持，本批先离线比较再按证据决定接入。

## 冻结与实现

- 原Query保持不变，各路候选最多5；A为当前三路RRF，B0为RRF先截前5再Cross-Encoder，B为三路候选完整并集去重后Cross-Encoder，C为当前商城全部同店/版本规则直接Cross-Encoder。B0用于检查过早截断，不是额外召回路径。
- 模型复用本机已有`BAAI/bge-reranker-base`，固定revision `2cfc18c9415c912f9d8155881c133215df768a70`，6个权重/tokenizer/config文件SHA在manifest；不下载新模型、不新增聊天API调用。
- 外部原始29问题与原18改写探针分别报告，复用66子块/缓存Query向量/已有CODEX_REVIEW依据集合。外部正式accuracy仍不声明盲测。商城3保存模型Query+6合成探针分别报告，6规则/店；不虚构新事实或改原Query。
- 必要依据在候选并集是否齐全、最终Top3/5完整覆盖、逐例退化和增量耗时分别保存；无答案/需澄清不计完整回答分母，PARTIAL逐例保留。评分标签不进入召回/模型输入。
- 精排输入为原正文，max_pair_tokens=512，逐对检查、超限拒绝、不静默截断；batch8，不用评分阈值过滤条件。每个case/候选策略执行两次独立forward，核对排名一致；三次预热另列，不当正式延迟。计时仅含候选去重、分词、模型推理/排序，不含前置召回/Query编码/模型加载，不是端到端SLA。

## 实际GPU环境与复现

实测NVIDIA GeForce RTX 5060 Laptop GPU，8151MiB，driver592.01。原`agent/.venv`为Python3.12.13、PyTorch2.14.0+cpu。准备阶段尝试安装官方同版本cu130 wheel到独立忽略目录，因1.9GiB下载慢而停止；随后尝试复用现有CUDA安装的目录，但CPython3.11/3.12二进制不兼容，加载报WinError126。两次尝试均未作为正式实验，也未修改原环境、锁或驱动。

正式方案为**本地stdio GPU子进程**：读取本机既有`E:/Code/servicedesk-agent-sft/.venv/Scripts/python.exe`，不安装/修改该环境；主评测仍使用项目原Python。子进程只接收Query/正文pair，不接触业务数据库、HTTP或聊天API。实际版本Python3.11.15、torch2.11.0+cu128、transformers5.14.1，FP32、TF32关闭、cuda:0、CUDA12.8 build。同一原revision权重，单logit sigmoid仅用于单调排序，分数不解释成概率或授权。

最初[CPU准备manifest](../../evals/customer-rag-v3/manifest.json)和[直接CUDA准备manifest](../../evals/customer-rag-v3/manifest-gpu.json)均**未运行**，原文件保留。正式实测使用独立冻结的[stdio GPU manifest](../../evals/customer-rag-v3/manifest-gpu-stdio.json)，记录两侧环境和源码/输入/模型hash；执行前后校验一致。若重跑须另用输出文件名（原结果拒绝覆盖），并确保对应GPU解释器/本地模型和原PG数据仍可用。

```powershell
docker start resolveflow-review-demo-postgres-1
agent/.venv/Scripts/python.exe scripts/customer_rag_rerank.py --manifest evals/customer-rag-v3/manifest-gpu-stdio.json --output reports/customer-rag-v3/gpu-results.json
docker stop resolveflow-review-demo-postgres-1
```

官方环境参考：[CUDA安装选择](https://pytorch.org/get-started/locally/)、[固定版本wheel索引](https://download.pytorch.org/whl/cu130/torch/)、[CUDA同步计时](https://docs.pytorch.org/docs/stable/notes/cuda.html)。本批没有同版本CPU/GPU受控速度对照，不声称硬件加速倍数。

## 实测结果

[完整机器结果](gpu-results.json)记录56条Query、177个case/策略记录、242次正式独立forward，另有3次预热；每case/策略两轮排名一致。外部29原问中17可回答、18继承改写中12可回答，非完整可回答题不进入下表分母；不是新独立盲测。表内指标为**全部必要依据在最终TopK齐全的题数**，不是最终回答正确率。

| 数据组 | A 当前RRF Top3 / Top5 | B0 截5再精排 Top3 / Top5 | B 完整并集精排 Top3 / Top5 | C 全规则精排 Top3 / Top5 |
| --- | --- | --- | --- | --- |
| 外部原问（17可回答） | 12/17 · 16/17 | 14/17 · 16/17 | 14/17 · 17/17 | 不适用 |
| 外部改写探针（12可回答） | 10/12 · 10/12 | 8/12 · 10/12 | 8/12 · 8/12 | 不适用 |
| 商城保存模型Query（3） | 3/3 · 3/3 | 3/3 · 3/3 | 3/3 · 3/3 | 3/3 · 3/3 |
| 商城合成探针（6） | 5/6 · 5/6 | 5/6 · 5/6 | 6/6 · 6/6 | 6/6 · 6/6 |

### 候选池与反例

[逐依据诊断](error-analysis.json)关联原始结果hash与原标注block/range，不向模型输入评分标签。

- 商城P02：`R-LOST-001`原dense第5，被RRF截5排除。B0无法找回；B与C把它放到第3，完整依据恢复。商城B和C本批所有Top5排名相同；其中7题并集已覆盖全部6规则，P01/P05仅5规则，全量模式多出的金额条款排第6。不能据此声称全量精排普遍优于召回。
- 外部S:JD03：必要数码日期规则在并集中，却不在RRF前5；B把该规则排到第4，Top5修复，Top3仍不齐。证明**完整候选再排**的价值，也说明只看头部相关性不足以保证多依据齐全。
- 外部原问B的Top3改善S:JD02、S:MI06、F:JD09，同时S:MI02定制品例外条款从第2退到第5，净增2题；Top5无退化。
- 外部P09同时询问赠品不完整与扣赠品款，两组必要依据中的不予退换条款被B排到第8；P10询问他店购买能否套本店政策，适用范围第1，但必要排除条款退到第6。A两题Top3都齐，B连Top5也不齐。B0也使两题Top3退化，只因池固定5条而保住Top5，不能解释为B0语义模型更好。
- 外部改写P03、P06必要依据在三路并集里就不齐（12题仅10题候选完整），精排无法补救。原问17题则全部在并集齐全。不能把全部失败归因于文档或模型任何单一环节。

### 增量延迟与显存

下面为每Query两轮耗时中位数，再在该组Query上取中位；包括候选去重、主端分词、stdio、GPU端分词/传输/forward、排序与同步，不含召回、Query编码、模型加载和答案生成。`gpu_predict_ms`另存每轮，包含GPU端分词和传输，并非纯CUDA kernel时间。

| 数据组 | B0增量中位 | B增量中位 | C增量中位 |
| --- | --- | --- | --- |
| 外部原问29 | 49.65ms | 83.00ms | 不适用 |
| 外部改写18 | 51.91ms | 87.97ms | 不适用 |
| 商城保存3 | 26.37ms | 28.27ms | 28.64ms |
| 商城合成6 | 26.47ms | 27.69ms | 28.13ms |

外部并集通常8–9对正文，商城6对。所有pair最大327tokens，实际未截断。实测峰值allocated约1.13GiB、reserved约1.32GiB；峰值统计从GPU模型加载后重置，包含预热和正式推理。正式子进程导入+加载15.08秒，主侧从导入到worker就绪28.51秒；预热首轮571.74ms，后两轮6.62/8.51ms（仅一对短文本，不能替代正式耗时）。**GPU热态精排成本可接受的假设得到支持，冷启动仍需单独处理**；不是整个Agent回答几十毫秒。

## 结论与下一步

本批不更换生产默认：商城口语P02有改善，外部原问净改善，但外部改写存在完整依据退化。现在应先做同文档父级/相邻关联条款的证据组装对照，重点验证例外、适用范围和多规则冲突；仍以可见Query/正文/结构为输入，不能按Gold补条款。P03/P06另查Query表达与召回表示，不靠精排掩盖候选缺失。下一批须另冻结方案和结果，再决定小语料全规则或候选并集精排如何接入。

本批完成的是离线固定Query实测与反例定位，未部署Cross-Encoder，未新跑Agent生成回答，未改查询生成或政策正文，未完成端到端体验复测。生产仍为正文dense+正文/标题BM25→RRF。

## 验证与收口

- 准备阶段缺模块红测、行宽修正和10项通过保留；GPU烟测确认真实cuda:0、有限分数后才开始正式实验。新增stdio协议输入/输出/设备耗时透传与worker提前退出测试后，实验、融合、Query、Agent、sources共**35通过，0失败/跳过**。
- 实际命令（agent目录）：`$env:PYTHONPATH='E:\Code\Agent+Backend'; .venv/Scripts/python.exe -m pytest tests/unit/test_customer_rerank_experiment.py tests/unit/test_support_retrieval.py tests/unit/test_support_query.py tests/unit/test_support_agent.py tests/unit/test_support_sources.py -q`。首次遗漏PYTHONPATH导致收集错误，补正确调用后通过，未为此改断言。
- 四实验源码使用仓库根运行`agent/.venv/Scripts/ruff.exe check --config agent/pyproject.toml ...`通过；测试Ruff在agent目录通过。一次在agent目录检查根脚本触发不同导入分类，另一次误用根相对路径找不到ruff；统一正确目录/配置后通过，未改冻结源码以迎合目录差异。
- 报告核对时“B/C全部排名与分数相同”断言失败：确认P01/P05并集只有5规则，全规则多出的第6条不影响Top5；已纠正文字并改为核验全部9题Top5一致，没有修改原结果。
- 仅临时启动保留PG，连接强制只读；11张public表全行数/hash前后相同（机器结果仅存见证，不存数据库原文）。输入/权重hash执行前后相同，无新聊天API/模型下载/业务写入。GPUworker正常退出后顺序停止PG，保留卷；停机端口/进程核验见[收口记录](completion.json)。原四历史脏文件保持，不夹带旧资产/临时下载/日志。
