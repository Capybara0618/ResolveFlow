# RAG结构、粒度与证据包优化（2026-10-06）

**本批完成两轮通用候选比较和可复用的来源查询入口。可采用的改进是完整来源集合精确去重；排序候选都有取舍，局部窗口还会漏条件，暂不替换生产dense或Java完整规则。** 这次不是宣称RAG全部优化完成，也没有重跑付费Agent。

规格在首轮运行前保存为[结构优化](../../docs/rag-structure-optimization.md)，第二轮的动机和运行前配置为[来源去重](../../docs/rag-source-union.md)。原29题和CODEX_REVIEW标签未改；新增18道在首轮测量前冻结的[改写/边界探针](../../evals/rag-structure-v1/probes.json)，12可完整回答、1部分可答、2需澄清、3语料外。探针是Codex同义改写，明确不是盲测或真实用户问法。

## 1. 实际构建的能力

- `scripts/policy_structure_candidates.py`：复用原文结构，识别18个短编号标题候选/列表引导句；来源块或表格行构造检索单位，前缀与正文共同检查实际BGE token长度。248个新子块最大367 token，原文跨度/表格行、搜索前缀分开。标题是版式推断，不是政策适用/冲突优先级；尚未采用为生产规则。
- 同源同快照内可按父正文或原文块/表格行聚合，不能合并不同版本/主体。一个长原文组的所有跨度与单个命中子块分开计分，避免把局部片段当作完整依据。
- RRF使用固定常数60、每路20候选，按排名融合，词法零分不贡献；不按题号、商品品牌或特定问法选政策，不添加新的模型/依赖。
- 完整包准入后按来源身份去重：保留全部原文与章节引用，复用已有来源目录、序列化和短引用校验。不是重新发明短引用或旧block-union算法，而是将已有能力接成任意查询入口，并在新来源标签下复核。
- 宜家生效/更新日期2024-08-09从原文定位提取为独立审查元数据；没有覆盖旧source manifest的null，也没有宣布该日期适用于本平台商家。

## 2. 两轮对照结果

第一轮复现旧BODY两路排名和分数（容差1e-6），测7候选×47题×前2/前5，共658记录；第二轮4候选×47题×前2/前5，共376记录。全部1034结果包含来源绑定，原题/探针和完整/局部回答分别汇总。

表中“直接”指命中子块确实包含一组完整块/表格行充分依据；“完整包”指原完整父章节准入后覆盖。“原题”分母17，“探针”分母12；不是全部29/18题回答准确率。

|候选|原题直接前2|原题直接前5|原题完整包前5|探针直接前5|探针完整包前5|
|---|---:|---:|---:|---:|---:|
|原BODY dense|7/17|13/17|16/17|9/12|11/12|
|原BODY BM25|10/17|13/17|17/17|9/12|12/12|
|BODY按相同父正文聚合|6/17|8/17|17/17|7/12|12/12|
|原子块＋路径dense|6/17|9/17|16/17|5/12|10/12|
|原子块＋路径BM25|8/17|9/17|17/17|6/12|12/12|
|原子块＋路径RRF|9/17|11/17|16/17|5/12|10/12|
|原66子块BODY＋RRF|10/17|12/17|17/17|9/12|12/12|
|原66子块＋章节路径dense|8/17|11/17|17/17|7/12|12/12|
|原66子块＋章节路径RRF|11/17|11/17|17/17|12/12|12/12|

第二轮的去重不改变上表检索命中或完整证据覆盖，只改变发送正文是否有重叠。第一轮[comparison-v1.json](comparison-v1.json)、第二轮[fusion-v1.json](fusion-v1.json)、[采用决定](decision.json)保留全部失败和配置。第二轮在看首轮结果后提出，属于开发过程，不能把它描述为预先独立盲测。

### 为什么不直接部署融合或原子块

原子块有更清楚的来源关系，却把原本同一个子块包含的多项条件拆散，在固定前5个位置下，多条件问题需要占更多名额；重复的通用路径也未必能改善BGE匹配。不能因为赠品一题找齐了，就忽略其他题退步。

原66子块上的融合补齐了赠品限制，BODY＋RRF的前五完整包由原题16→17、探针11→12；但是原题前五直接覆盖13→12。路径＋RRF前二改善、探针前五也改善，原题前五直接覆盖却为11。没有候选在所有本批关注指标上稳定优于原dense，因此**本次生产不切换**。这不是运行错误，是真实效果取舍；不为了单例或满分继续改参数/标签。

按相同父正文聚合使展开全覆盖，却让直接覆盖13→8、平均完整包正文token2522.47→2996.18；它也不是免费的排序优化。生产本来就按Java规则聚合子块，不把这个实验说成新实现了生产去重。

### 为什么不采用相邻块窗口

第一轮直接裁成“命中块＋标题/引导句＋邻居”的局部包，原dense前五只覆盖14/17题；原子融合的局部包13/17，探针7/12。内容更短不代表完整，尤其会丢失跨章节适用范围/例外。全部局部包标`complete_policy_guaranteed=false`，不拿它替换审批依据。

短编号推断还有语义层次风险：例如总则日期判定标题之后又出现长的无理由退货引导段，单靠编号长度规则不能证明后续例外还属于“日期判定”。因此新增18个候选标题和原子向量仅供审计/比较，未强行写进权威政策。后续应先核查结构分组，不能靠删除冲突块提高分数。

## 3. 确定保留的收益：同一完整来源集合去重

BODY dense排名/准入不变，将已准入的重复源块只发送一次：

|前5完整包正文|去重前平均token|去重后平均token|减少|覆盖是否改变|
|---|---:|---:|---:|---|
|原17道完整可答题|2522.47|2003.35|20.58%|仍16/17|
|12道完整可答改写|2350.33|1840.25|21.70%|仍11/12|

全部第二轮376份结果逐一确认原文集合相同、覆盖相同、文本/本地token不增加。按source_id/raw_sha256/block_id识别，不能仅凭相同文字把不同版本/主体并起来。准入仍按原8000字符执行，不因去重腾出空间追加材料。

这是固定DeepSeek tokenizer对原文正文的本地测量，不含请求系统规则、工具协议或引用JSON包装，**不是API账单或整个Agent的token节省**。此前短引用实验的70%多是另一种包含元数据的序列化比较，本次20.58%不可与之相加。当前生产Java规则返回粒度不同，不把外部文档收益写成生产效果。

## 4. 可体验的来源查询入口

新增`scripts/policy_document_search.py`接通任意query→来源主体/快照过滤→真实本地BGE→可选固定融合→完整父章节准入→源块去重→短引用/可信来源账本→逐引用回查。复用已有工程，不创建额外MCP、服务或数据库。

默认dense；融合须用显式`--strategy body-rrf`或`path-rrf`，输出标明实验排名。命中材料不是答案：本工具不输出可退/不可退判断，也不声称测过拒答率。只能单个外部主体，可选其多个来源快照，不允许跨主体混搜或自动采用为商家政策。完整原文输出须放忽略的tmp，缓存缺失/哈希变化明确失败。

```powershell
agent/.venv/Scripts/python.exe scripts/policy_document_search.py --source mi-self-operated --query '小米有品主商品想退，赠送的东西已经用掉了。政策一处写赠品不完整，一处写扣赠品钱，这两处要怎样一并看？' --strategy body-rrf --output tmp/rag-structure-v1/search-new.json
```

实际执行同一探针P09，`--output tmp/rag-structure-v1/search-gift-rrf.json`：2994本地packet token，b0026（不受理引导）、b0032（赠品不完整）、b0082（扣价）都在完整可信账本，所有短引用逐项回查通过。没有调用DeepSeek、审批或业务写入。这是本机来源查询实测，不是32例整体Agent验收。

## 5. 实际命令、失败与未运行

```powershell
# 首轮真实本地BGE，输出不可覆盖；缓存包含原文/向量，必须在tmp
agent/.venv/Scripts/python.exe scripts/policy_structure_eval.py --cache tmp/rag-structure-v1/vectors-v1.json --output reports/rag-structure-v1/comparison-v1.json
# 再次复算复用缓存，不调用encoder；输出选择新文件名
agent/.venv/Scripts/python.exe scripts/policy_structure_eval.py --reuse-cache --cache tmp/rag-structure-v1/vectors-v1.json --output tmp/rag-structure-v1/comparison-repeat.json
agent/.venv/Scripts/python.exe scripts/policy_fusion_eval.py --output reports/rag-structure-v1/fusion-v1.json
agent/.venv/Scripts/python.exe scripts/policy_fusion_eval.py --output tmp/rag-structure-v1/fusion-repeat.json
# 本批相关集中验证；196项及另13项短引用，未跑全仓
agent/.venv/Scripts/python.exe -m pytest -q agent/tests/unit/test_policy_structure_candidates.py agent/tests/unit/test_policy_fusion_eval.py agent/tests/unit/test_policy_document_search.py agent/tests/unit/test_policy_codex_review.py agent/tests/unit/test_policy_query_eval.py agent/tests/unit/test_policy_context_packet_eval.py agent/tests/unit/test_policy_semantic_score.py agent/tests/unit/test_policy_representation_eval.py agent/tests/unit/test_policy_chunks.py agent/tests/unit/test_policy_documents.py --junitxml=tmp/rag-structure-v1/unit-tests-final.xml
agent/.venv/Scripts/python.exe -m pytest -q agent/tests/unit/test_policy_short_packets.py
agent/.venv/Scripts/python.exe -m ruff check --config agent/pyproject.toml scripts/policy_structure_candidates.py scripts/policy_structure_eval.py scripts/policy_fusion_eval.py scripts/policy_document_search.py agent/tests/unit/test_policy_structure_candidates.py agent/tests/unit/test_policy_fusion_eval.py agent/tests/unit/test_policy_document_search.py
```

- 第一轮运行前冻结33输入/7候选/18探针；第二轮冻结38输入/4候选，含首轮报告与已保存向量SHA。29个原query/Gold/原模型判断、4份HTML、原66子块及旧检索代码字节保持。第一轮47query向量批次0.293s、248候选向量批次2.354s，不含加载/准备；第二轮无新embedding。真实本地BGE仍固定原模型/revision/512维。
- 两次复算所有排名、覆盖、来源包/引用及hash相同，剔除真实测量耗时后报告一致。排名耗时口径分别注明，未包含embedding/序列化/DB网络；不将两个口径用来宣称生产加速。
- 集中`pytest -q`覆盖新结构/融合/查询入口及既有来源/跨度/表示/评分/原文解析，共196 passed/0 failed/0 skipped，2.19s；另已有短引用13 passed，0.33s。合计209不同相关项，其中新增37（结构22、融合6、查询9）。JUnit `tmp/rag-structure-v1/unit-tests-final.xml`；后13项单独控制台验证。
- 新测试覆盖长正文/前缀总窗口与末尾条件、表格/跨度沿用14项来源检查、同源不同版本不合并、零分不影响RRF、局部包范围及不完整标记、去重不隐去坏hash、探针不覆盖原query、查询范围/参数拒绝。Ruff、本地链接及Git差异检查通过。
- 实际Lint使用`agent/.venv/Scripts/python.exe -m ruff check --config agent/pyproject.toml`并显式列出本批4脚本/3测试。收口时漏写`--config`的根目录检查误加载环境配置，报告30项import/未启用E402的noqa问题；同一源码按本项目配置重跑通过，未改冻结runner或规避项目规则。
- 初次Ruff报告import/长行，格式修正并在正式测量前刷新本批冻结runner hash；无已完成报告被覆盖。末次集中测试一度引用不存在的`test_policy_short_packet_eval.py`，0项运行/明确失败，纠正为实际`test_policy_short_packets.py`后196＋13项通过。两次补丁因上下文不匹配未生效，读取实际行后重新应用，不把失败命令记成通过。
- **没有**生产索引/数据库迁移、模型API调用、Agent提示/query改写、退款操作或完整32例对照；未运行全仓、Java/浏览器、mypy。历史16个mypy诊断、旧测试目录8可见失败仍不属于本批209项通过结论。原四历史脏文件、图与日志保留、不夹带。

## 6. 后续顺序与个人项目取舍

先审查已保存的真实Agent query和商家政策返回，区分查询缺事实、结构分组问题与排名问题；这一步可复用记录，不默认收费。将可复用源结构/去重能力接入实际商家文档流程，需要明确原文到Java完整规则的权威边界，不能让外部来源获得退款授权。

本次排序候选只能作为开发证据。若后续实际query同样出现语义排序不足，再固定候选比较更合适的表示或小范围重排；无需继续网格调参追29题满分。RAG候选和引用流程稳定后，才做相同业务输入/模型参数的整体Agent对照。尚未宣布Agent侧优化完成。

可迁移的经验是：**结构更细、融合更多、文本更短都不是天然更好；先检查必要条件，再比较同一证据集合，才能把效果和成本的变化解释清楚。**
