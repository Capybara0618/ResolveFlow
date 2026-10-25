# 扩展售后政策RAG评测准备

2026-10-25，用户授权准备新数据集与四组入口，暂未运行新题排名、GPU精排或生成答案。Agent冻结稿与生产入口保持。

## 来源小步

- [方案](../../docs/customer-rag-quantification-v3.md)、[来源清单](../../evals/customer-rag-quantification-v3/sources.json)、[带原文定位的正文](../../evals/customer-rag-quantification-v3/corpus.json)已生成。15份HTML/7品牌域/939正文块/74247字符：原4份冻结快照+新增11份官方页面，URL/原字节hash/抓取日期可追溯。原始HTML仍在忽略tmp，不提交网站脚本、cookie或原始日志。
- 优衣库FAQ请求HTTP200但仅返回React页面外壳，无政策正文，已明确排除；改用可直接保存的索尼三包页面，不拿搜索摘要伪造完整正文。候选地址及失败快照保存在本机tmp，仅报告排除原因。
- 新提取器对明确正文根解析，保留原快照字符偏移、原文片段hash、表格及章节，不修改旧解析器。Apple页面有无关祖先noscript干扰旧遍历，通过独立定位唯一正文根后解析原始片段，逐块重新校验原HTML位置；不靠改写原HTML绕过hash。
- 先缺模块收集失败，接通后3单元通过；两项Ruff导入排序失败经自动整理修正。实际命令：`python -m pytest agent/tests/unit/test_customer_rag_dataset_v3.py -q --basetemp .pytest-tmp/rag-v3-data-green`、`python -m ruff check scripts/customer_rag_dataset_v3.py agent/tests/unit/test_customer_rag_dataset_v3.py`、`python -m scripts.customer_rag_dataset_v3 build`及`check`。check重建正文与原始HTML逐项一致。
- 文档有效日期缺失不补造，抓取时间不是政策生效时间；公开参考不发布为项目商家规则。品牌过滤后每题候选不同，后续报告实际规模。

来源小步只证明提取；未测新质量/时延。0生成API、未改Agent/线上RAG/业务数据库或启停服务。

## 问题与标签小步

[问题索引](../../evals/customer-rag-quantification-v3/README.md)/[100题与Gold](../../evals/customer-rag-quantification-v3/queries.json)/[数据审计](dataset-audit.json)已完成：五类各20，40开发（32可答）/60验收（48可答），103条原文跨度，15文档均有可答题。开发证据来自京东/有品3篇，其余12篇用于验收题，两组来源不重叠；作者见过原文，且部分文档沿旧数据，不称全新独立盲测。

每题包含品牌全范围scope、答案要点、必要原文及hash；20无法回答中8政策缺口/12实时业务或私有事实缺失，不从排名分数直接算拒答正确率。所有答案要点须在后续真实回答中逐项源审，关键词匹配不代替语义评分。

先模块缺失失败，再6检查通过（真实100题矩阵、造假quote、只选正确单篇scope、跨组变化、无缺失原因、重复ID拒绝），Ruff导入排序1项修正。`python -m scripts.customer_rag_questions_v3`实际核验全部103跨度逐字/hash一致、40/60及每类分层、原文来源不跨组。首次编写发现表格单元分隔符是` | `而非换行，按原表格第一行及表头修正引用后才写最终问题文件；没有运行排名后换题。

问题小步完成时尚未运行新题排名/答案/速度，0生成API，Agent与生产保持。

## 四路入口与索引准备完成

[共享切块/检索/组装](../../scripts/evaluation/customer_policy_benchmark_v3.py)、[运行入口](../../scripts/customer_rag_benchmark_v3.py)、[准备记录](preparation.json)已完成。15份正文统一切为344片段，512维BGE真实文档向量已在本地CPU编码并保存忽略缓存；没有预先计算或缓存新题Query排名。每题先按品牌全范围过滤，实际候选为京东10、有品15、华为24、宜家48、Apple50、三星9、索尼188片段；这不是每题在344片段里竞逐，语料规模不均须随最终结果说明。

四路为dense、BM25、正文dense+正文BM25正分候选RRF、相同RRF候选CrossEncoder。固定每路候选20，融合常数60，最终Top3，预算8000字符/4096本地tokens；去重复跨度，不展开父级。章节/标题前缀固定64字符，长表格重复真实首行跨度而非模型推测列含义。所有方法用相同预处理，不额外给精排组更多正文。

[窗口审计](preparation.json)：344文档片段最大341 embedding tokens；100题Query最大45；全部品牌范围内3733个潜在CE输入仅分词检查，最大316/512，0静默截断。[容量检查](evidence-capacity.json)使用Gold寻找最少原文片段，仅证明80可答题的必要跨度可在最多3片段内呈现，非检索策略、不是命中率100%，Gold不进入检索输入。

工程先缺模块失败，再发现表头首行与正文之间换行未进入跨度，造成一条原文完整证据不能被覆盖。已将换行绑定回原跨度，保留全部Gold，19相关检查通过；闭包绑定和导入Ruff问题已修。测试涵盖全部103跨度保留、品牌scope先过滤、Gold不进入公开Query、CE处理实际候选、片段预算/去重、缺矩阵/重复/非法时延拒绝、均值与中位数分开；8个新增文件Ruff通过。既有Starlette/anyio弃用警告保留，没有为它修改依赖锁。

### 实际GPU通用确认及一次计时修正

[首次通用确认](generic-smoke.json)4路均实际成功，RTX5060 Laptop、CUDA12.8、FP32、TF32关闭。发现BM25第一次调用约676ms，其中jieba冷加载约620ms；旧记录保留，这不能作为热态检索速度。新入口把词法初始化和8个通用CE候选放进启动预热，[修正后的4路确认](generic-smoke-warm.json)通过，实际10候选精排与来源包预算检查成功。

这两次均只用不在100题中的通用问题，未运行开发/验收题排名，也不把一条问题的耗时当总体性能。两次共8本地检索、29个CE配对（首次1预热+10候选，修正8预热+10候选）、0生成API。初次代码/协议按原hash归档于[初始驱动](initial-driver.py.txt)/[初始协议](initial-protocol.md.txt)，原manifest.json不改；当前以[manifest-v2.json](../../evals/customer-rag-quantification-v3/manifest-v2.json)为正式准备版本。后续代码变化须另建manifest，不覆盖旧成绩。

### 命令与尚未执行

仓库根PowerShell，使用原项目虚拟环境和已有本地模型：

```powershell
$env:PYTHONPATH="$PWD;$PWD/agent/src"
agent/.venv/Scripts/python.exe -m scripts.customer_rag_benchmark_v3 check
# 以下为后续正式测量命令，本批没有运行：
agent/.venv/Scripts/python.exe -m scripts.customer_rag_benchmark_v3 execute --split development --output reports/customer-rag-quantification-v3/development.json
agent/.venv/Scripts/python.exe -m scripts.customer_rag_benchmark_v3 execute --split acceptance --output reports/customer-rag-quantification-v3/acceptance.json
```

开发40×4×3=480次，验收60×4×3=720次；质量每题只计一次，重复用于稳定性及速度。结果逐请求写新jsonl，完成后输出完整矩阵/分项汇总，禁止覆盖已有输出；异常保留已执行记录。主比较hybrid-rrf-ce对dense，BM25强对照同时报告。先在开发题诊断，确定最终方案后再运行验收；如调整任何方案，需新的源码冻结及对应报告。

尚未测出v3的完整证据命中率、回答准确率或总体平均/P95；LLM回答只完成评分协议，未实现/运行收费回答驱动。线上仍保持原小政策策略，Agent冻结稿/PDF不改，不能把本离线实验入口称为生产已切混合精排。
