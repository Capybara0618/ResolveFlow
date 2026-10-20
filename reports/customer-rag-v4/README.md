# 客服RAG第四批：保留锚点、完整父级与短引用

2026-10-20。用户批准接续架构后的证据组装验证。结论是：本批固定外部长文档中，**RRF锚点优先、预算内补完整父级**比继续叠加Cross-Encoder更稳定；生产商城仍返回完整规则，本批没有替换线上排序或把外部来源导入商家政策。

## 1. 实际实施与冻结

[规格](../../docs/customer-rag-evidence-v1.md)和[manifest](../../evals/customer-rag-v4/manifest.json)在测量前冻结，复用第三批实际GPU排名、原Query、原来源/父级绑定及原CODEX_REVIEW依据集合。47题为29原问+18继承改写，其中17/12可完整回答；均是已查看开发数据，不是独立盲测。商城9条既有模型Query/合成探针仅携带原结果，未做新推理。

新增`customer_evidence.py`只接收已选子块、源文档索引和范围，不接Query或评分标签。复用既有`context_refs`及表格表示：先完整准入命中跨度，再整体准入其已有完整父级；超预算跳过父级，保留已准入原跨度。按来源/快照/源块/表格行合并重叠跨度，间隙不补造，不按文本相同合并跨来源。所有新增内容都有原文位置、hash和父级绑定。

正文统一上限8000字符且4096本地DeepSeek tokenizer token；并非整个模型请求上限。RRF/CE分别取前3和5个锚点；dual先RRF再补未重复CE，实际前3有3–6个、前5有5–8个锚点，不能当同候选数量的免费收益。每策略/题/入口重新组装两次，共470条记录/940次组装，packet和来源跨度完全一致。直接跨度覆盖逐条复现第三批原分数；全部已准入锚点的每段原文都留在最终包中。

## 2. 完整证据包覆盖

[完整结果压缩存档](results.json.gz)保留逐条来源跨度、hash、父级准入/阻塞、耗时和评分，解压与本地原始`results.json`字节完全相同；避免提交21万行重复证明元数据。下表是“全部必要依据在最终证据包里齐全的题数”，展开后不能叫Recall@K；不代表最终回答准确率。

| 策略 | 原问：3锚点入口 | 改写：3锚点入口 | 原问：5锚点入口 | 改写：5锚点入口 |
| --- | --- | --- | --- | --- |
| RRF直接跨度 | 12/17 | 10/12 | 16/17 | 10/12 |
| GPU CE直接跨度 | 14/17 | 8/12 | 17/17 | 8/12 |
| RRF锚点＋完整父级 | **16/17** | **12/12** | **17/17** | **12/12** |
| CE锚点＋完整父级 | 16/17 | 9/12 | 17/17 | 11/12 |
| 双路锚点＋完整父级 | 16/17 | 12/12 | 17/17 | 12/12 |

RRF父级展开在全部ANSWERABLE题的两种入口下均无相对RRF直接跨度退化；CE展开也不删除自身已准入跨度，但它的锚点本来就可能缺关键章节，父级不能任意跳到不相关章节找Gold。双路没有比RRF父级更好，本批不为它增加默认复杂度。

### 关键反例

- P09赠品冲突：RRF命中了“不予退换”和“扣赠品价款”两侧，完整父级后齐全；CE前5没有足以绑定不予退换父级的锚点，即使展开仍不齐。单靠父级也不能修复所有排序问题。
- P10他店购买/本店适用范围：CE直接前5遗漏排除条款，父级展开后恢复；RRF原本就齐。
- S:MI02定制品例外：CE前三直接遗漏，父级补齐；原先RRF前三已齐。
- S:MI04赠品：RRF前三父级仍缺，是原问前三入口唯一未完整题；前5入口恢复。没有为这题按Gold新增关联边。
- P03/P06：必要跨度未进入各路前5，但命中的其他同父级内容能读回对应规则，RRF父级两题均恢复。说明候选缺失与来源读回是不同层次，不能把候选池里的漏项直接断言为“原文没有”。

### P03/P06只读排名归因

诊断位于结果`diagnostics`，评分标签只用于解释完整排名，不参与选择。

| 探针 | 必要原文 | dense完整前缀 | 正分正文BM25完整前缀 | 正分标题BM25完整前缀 |
| --- | --- | --- | --- | --- |
| P03日期口语 | 数码规则“实际收到商品第二日起” | 7 | 11 | 10 |
| P06质量故障往返运费 | 质量故障表格行 | 8 | 4 | 16 |
| P06质量故障往返运费 | 质量问题双方运费条款 | 7 | 6 | 19 |

各路窗口5→10后，两题候选并集都从不齐变齐：P03并集7→11条，P06为11→15条；窗口20也齐。P03的11条已经覆盖其范围内全部检索子块，因此不能据两题把“增大窗口”宣称为通用最优。原文存在，本批发现的是窗口/排序与结构读回问题；没有证明Query改写无用，也未改写原问题。

## 3. 成本与既有短引用复用

以下中位数以各组全部29/18题计算，不只取可回答题；仅本地组装、来源验证与分词，包含实验里的重复原文检查，不是生产工具或Agent端到端延迟。

| 5锚点入口 | 原问正文token中位 | 改写正文token中位 | 原问组装中位 | 改写组装中位 |
| --- | --- | --- | --- | --- |
| RRF直接跨度 | 791 | 889.5 | 21.71ms | 22.12ms |
| RRF完整父级 | 1373 | 1373 | 45.12ms | 49.79ms |
| CE完整父级 | 1373 | 1373 | 44.84ms | 47.35ms |
| 双路完整父级 | 1373 | 1373 | 49.91ms | 48.82ms |

470包最大正文3946tokens/6773字符，无直接锚点因预算被拒。S:IK06/P15的10513字符文档级父级被明确拒绝，CE/双路保留直接原文；S:IK03双路因累计上限拒绝一个送货父级，没有静默裁剪或更改评分。

现有父级有些接近整份政策，例如京东约千字整篇、小米约两千多字关联包。覆盖提高伴随更多原文和可能不相关内容；不是新设计出了精确的语义关系图，更不是独立审核了父级适用性。后续需要保留这种成本意识，不能只追满覆盖。

原始诊断包带完整hash/跨度时，RRF父级的序列化中位约9410tokens，不能把正文1373tokens当实际传输量。**看到该结果后**，另冻结[短引用序列化manifest](../../evals/customer-rag-v4/wire-manifest.json)，复用已有`policy_short_packet_eval.compact/resolve`做同一信息集合的序列化比较；不重选文本、不改分数，详见[短引用结果](wire-results.json)。

| 同一5锚点RRF父级证据 | 原问中位token | 改写中位token |
| --- | --- | --- |
| 完整证明元数据包 | 9884 | 9890 |
| 原有短引用格式发给模型 | **2241** | **2241** |

此表完整包是在既有引用协议中重建后的包，与上一段诊断JSON格式不同。完整来源/hash/位置留在外部可信ledger，模型收到短编号及相同原文；470包逐一经C0回查全部源块，原文/顺序/来源/跨度完全一致。C0明确标为“检索证据（不代表完整政策）”，不是把所选材料冒称为完整政策或裁定依据。

短包最大值：RRF父级4320tokens、CE父级4550、双路5080；因此正文4096上限不能代替完整请求预算。RRF父级有S:MI03/S:IK02/S:IK06/P06/P15五包短序列化超过4096，已保留，没有改预算/改评分来隐藏。以上均为本地tokenizer统计，不是API账单或本次线上token节省；复用的是已有短引用能力。

## 4. 对架构的落实判断

可以固定的职责是：Agent按需生成Query→限定商家/版本→三路召回/RRF→命中锚点→预算内读取关联完整依据→源文去重与短引用→Agent综合回答。排序负责找到入口，组装负责保留条件与例外，两层分别验证。

- 长文档实验优先保留RRF锚点和完整结构读回；本批证据不支持把CE或双路合并设为默认。
- 商城现有索引已经按命中子块返回完整Java政策规则；本批外部文档的父级扩展不直接接进它，更不能用整份外部政策给商家授权。商城P02漏主规则问题仍是第三批CE候选改善，尚未上线。
- 独立、较小的章节/规则关系仍需受控来源结构支持，不能在线靠Gold或模型随意编关系。对于超过请求预算的完整依据，应明确缺口并按需读回，而非裁掉例外。
- 本批完成开发对照与来源/成本验证，未新增真实Agent回答、Query改写、商家政策发布、数据库迁移或浏览器联调。下一实际业务验证应围绕当前商城完整规则是否被正确组合与回答展开；不能声称客服RAG质量已经整体验收。

## 5. 实际命令、验证与收口

```powershell
# 源码/规格/输入冻结后执行；输出拒绝覆盖
agent/.venv/Scripts/python.exe scripts/customer_rag_evidence.py --freeze
agent/.venv/Scripts/python.exe scripts/customer_rag_evidence.py --output reports/customer-rag-v4/results.json
# 看到元数据成本后独立冻结，只改变序列化
agent/.venv/Scripts/python.exe scripts/customer_rag_evidence_wire.py --freeze
agent/.venv/Scripts/python.exe scripts/customer_rag_evidence_wire.py --output reports/customer-rag-v4/wire-results.json
```

原始`results.json`在本机保留，Git提交其gzip存档；在新checkout需要读取/核验冻结结果时，先恢复该文件（已存在则拒绝覆盖），不要重新测量来冒充原计时记录：

```powershell
@'
import gzip
from pathlib import Path
p = Path('reports/customer-rag-v4/results.json')
with p.open('xb') as stream:
    stream.write(gzip.decompress(p.with_suffix('.json.gz').read_bytes()))
'@ | agent/.venv/Scripts/python.exe -
```

- 关键失败测试先缺模块收集失败；实现后9个新边界项通过，和既有精排/完整父级/子块共78通过。修正一处B023闭包捕获后，在正式测量前冻结，没有修改旧报告/Gold。
- 最终agent目录执行`$env:PYTHONPATH='E:\Code\Agent+Backend'; .venv/Scripts/python.exe -m pytest tests/unit/test_customer_evidence.py tests/unit/test_customer_rerank_experiment.py tests/unit/test_policy_context_packet_eval.py tests/unit/test_policy_chunks.py tests/unit/test_policy_short_packets.py tests/unit/test_support_retrieval.py tests/unit/test_support_query.py tests/unit/test_support_agent.py tests/unit/test_support_sources.py -q`：**120通过、0失败/跳过**。不是全仓测试。
- 三个本批源码在根目录用`ruff check --config agent/pyproject.toml`通过，新测试在agent目录Ruff通过。一次误读不存在的`policy_short_packets.py`未运行，随后定位实际`policy_short_packet_eval.py`并复用，没有引入第二套引用协议。
- 470包两轮同结果/原锚点跨度保留/直接分数复现，以及470短引用包原文/来源回查均通过；完整结果的元数据只留公开来源/模拟问题及跨度hash，无数据库快照或密钥。
- 准备步c83cdd9已正常推送并确认。当前输入/模型hash与两manifest保持，生产实现/依赖锁/原四历史脏文件保持。本批没有启动数据库、GPUworker、生成模型或业务服务；端口/进程和最终证据见[收口记录](completion.json)。结果与本步源码/文档精确提交正常push后核实远端，SHA见本轮回复。
