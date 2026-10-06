# 原始政策逐查询诊断 v1

2026-10-06，固定4份官方HTML/3来源家族、242结构块和66检索子块，独立于旧calibrated-v3/66待审query。当前29问/41依据原子：11条复用已经冻结的京东官方FAQ原话，18条Codex阅读资料后编写的结构诊断。不是29个真实用户日志、随机抽样或独立盲测；两页京东同一家族，当前没有训练/测试拆分或未见来源的泛化结论。

## 数据与标注边界

- `manifest.json`在本轮排名前生成，冻结queries/evidence字节、原草稿/实际子块输出及既有FAQ manifest；旧FAQ文件不改、不再次分配到三个模拟商家。这里的主体是EXTERNAL:JD/MIYOUPIN/IKEA_CN，不是商家已采用的政策版本。
- `queries.json`每问包含query、来源、精确主体/原文快照范围、独立的draft与review。FAQ来自旧官方页面，答案未拷入新语料；可能没有答案是合理结果。合成问法与标签均是Codex草稿，不能作为独立Gold。
- `evidence.json`保存所需依据的原文block/表格row/字符区间/hash，不保存版权全文，不指向“应该排第几”的chunk ID。普通段落区间针对解析块文本；表格行区间针对固定canonical列名和值表示，绑定表示hash及原整表hash。原始HTML位置仍通过block定位回查。切分改变时同一来源依据可复用；表示改变须明确迁移/重新确认，不能静默改坐标。
- 所有review均PENDING、labels/reviewer/origin均null。draft的17 ANSWERABLE、1 PARTIAL、3 NEEDS_CLARIFICATION、8 NOT_IN_CORPUS是待审分布，不是正式答案分布。近似但不足的条款不一律意味着非法条款，更不能根据这些检索标签决定退款审批。

## 运行与复核

从仓库根目录执行，输出必须是新文件，依赖既有本机原文/草稿/子块缓存和固定本地BGE；无需Docker/API密钥：

```powershell
# 无排名、无草稿标签的完整来源包，仅保存于忽略tmp，不运行embedding。
agent/.venv/Scripts/python.exe scripts/policy_query_eval.py --prepare-review --output tmp/policy-documents-v1/query-review-next.json
# 待审诊断：真实本地dense与现有BM25，正式指标保持null。
agent/.venv/Scripts/python.exe scripts/policy_query_eval.py --context-chars 8000 --output tmp/policy-documents-v1/query-baseline-next.json
# 正式质量门禁：当前会明确失败，不创建报告、不调用模型。
agent/.venv/Scripts/python.exe scripts/policy_query_eval.py --require-reviewed --output tmp/policy-documents-v1/query-reviewed-next.json
```

当前本机复核包为`tmp/policy-documents-v1/query-review-v1.json`。它包含全部242来源块而非仅预选41原子，问题只带问法/来源/范围，不带draft答案或排名。解析/表头等仍为Codex结构草稿，应结合原HTML复核；这些问题已经由作者看过来源，包里隐藏标签不等于数据变成盲测。

独立复核者先阅读问题与完整来源，确定能否回答以及所需条件/例外；不要先看排名来选Gold。定义：ANSWERABLE为指定语料可以给出有条件的政策说明；PARTIAL为只有相关依据不能完整回答；NEEDS_CLARIFICATION为缺个案事实；NOT_IN_CORPUS为指定快照没有必要信息。涉及范围外取消/换货/运费等只测检索，不能给Agent新增动作。多文档日期/赠品规定存在张力时记录条件，不自行编造政策效力。

确认labels时另建新版本目录，保留当前冻结文件；review.state=APPROVED、origin=INDEPENDENT_HUMAN并填写真实复核者代号及独立labels。可沿用或追加依据原子，不限于作者预选41条。程序检查来源/区间/hash与标签结构，不能自动证明复核者身份或业务判断正确。若只是作者或另一模型检查，仍保持PENDING；质量门禁不能用伪造人审通过。

## 评分与体积

前2/5的直接覆盖要求所需字符区间全部被命中片段的并集覆盖：仅同block ID、部分长段或重复重叠不能刷分。表格行、主体、原文快照须一致。支持短证据区间，避免强制整段才算命中；原子粒度仍由标注者决定。

扩展覆盖只计成功导出的完整上下文；按排名顺序贪心返回，context ID及完全相同来源/快照/text hash去重，总字符上限包括分隔符，超限整份拒绝。不同context有部分重叠时目前仍保留，各自文本计入预算；这不是最优上下文选择或完整生产token装配。返回整个章节提高覆盖时必须同时看exported_chars；仅按字符控制，不宣称LLM请求必定不超token窗口。

正式all-required直接/扩展指标仅对APPROVED且ANSWERABLE的问题计算。其他类型没有空集合自动通过；检索器通常总会返回近邻，不能把有近邻等同有答案。本脚本不做阈值拒答或LLM回答，因此abstention_accuracy保持null；无答案/澄清题只展示候选供后续判断层评测。draft结果逐问展示但不计正式准确率。

当前基线/[实际命令与失败](../../reports/policy-document-ingestion/README.md)已记录。后续实验另冻manifest绑定新子块，但query/evidence及复核标签hash须保持相同才能受控比较；不得先看失败改答案再宣称改前改后提升。3来源家族不足以声称真实商家泛化，仍需更独立问法与复核证据。
